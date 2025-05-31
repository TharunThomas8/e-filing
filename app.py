from flask import Flask, render_template, request, abort
from docx import Document
from datetime import datetime
import os
import tempfile
import io
import boto3
from botocore.exceptions import NoCredentialsError
from dotenv import load_dotenv
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from form_fields import FIELDS
from s3_bucketHandler import serve_s3_file_as_attachment

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

@dataclass
class AppConfig:
    """Application configuration class"""
    bucket_name: str = "efiling-store"
    template_file: str = "template.docx"
    templates: Dict[str, str] = field(default_factory=lambda: {
        "docket-template": "docket_template.docx",
        "e-stamping-template": "e_stamping_template.docx",
        "Intex-template": "Intex_template.docx",
        "notice-to-all-respondants-template": "notice_to_all_respondants_template.docx",
        "process-memo-template": "process_memo_template.docx",
        "vakkalath-template": "vakkalath_template.docx"
        
    })
    output_prefix: str = "/output/"
    host: str = "0.0.0.0"
    port: int = 5000
    debug: bool = False

class DocumentProcessor:
    """Handles document processing operations"""
    
    def __init__(self, s3_client, bucket_name: str):
        self.s3_client = s3_client
        self.bucket_name = bucket_name
    
    @staticmethod
    def get_custom_datetime_format() -> str:
        """Generate custom datetime format for filenames"""
        return datetime.now().strftime("%d_%m_%YT%H_%M_%S")
    
    @staticmethod
    def get_formatted_current_date() -> str:
        """Get formatted current date with ordinal suffix"""
        def get_ordinal_suffix(day: int) -> str:
            if 11 <= day <= 13:
                return 'th'
            return {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
        
        now = datetime.now()
        day = now.day
        suffix = get_ordinal_suffix(day)
        return f"{day}{suffix} {now.strftime('%B, %Y')}"
    
    @staticmethod
    def convert_date_format(date_str: str) -> str:
        """Convert date from YYYY-MM-DD to DD/MM/YYYY format"""
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").strftime("%d/%m/%Y")
        except (ValueError, TypeError) as e:
            logger.warning(f"Date conversion failed for {date_str}: {e}")
            return date_str or ""
    
    def _replace_text_in_docx(self, doc: Document, replacements: Dict[str, str]) -> None:
        """Replace text in document paragraphs and tables"""
        # Replace text in paragraphs
        for paragraph in doc.paragraphs:
            original_text = paragraph.text
            for old_text, new_text in replacements.items():
                if old_text in original_text:
                    paragraph.text = original_text.replace(old_text, str(new_text))
                    original_text = paragraph.text
        
        # Replace text in tables
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    original_text = cell.text
                    for old_text, new_text in replacements.items():
                        if old_text in original_text:
                            cell.text = original_text.replace(old_text, str(new_text))
                            original_text = cell.text
    
    def process_docx(self, template_path: str, replacements: Dict[str, str], output_path: str) -> bool:
        """Process DOCX template with replacements and upload to S3"""
        try:
            if not os.path.exists(template_path):
                logger.error(f"Template file not found: {template_path}")
                return False
            
            doc = Document(template_path)
            self._replace_text_in_docx(doc, replacements)
            
            # Save to in-memory buffer
            output_stream = io.BytesIO()
            doc.save(output_stream)
            output_stream.seek(0)
            
            # Upload to S3
            self.s3_client.upload_fileobj(output_stream, self.bucket_name, output_path)
            logger.info(f"Document successfully processed and uploaded: {output_path}")
            return True
            
        except FileNotFoundError as e:
            logger.error(f"Template file not found: {e}")
            return False
        except Exception as e:
            logger.error(f"Document processing failed: {e}")
            return False

class FormDataProcessor:
    """Handles form data processing and validation"""
    
    @staticmethod
    def validate_form_data(data: Dict[str, Any]) -> bool:
        """Validate required form fields"""
        required_fields = [field["name"] for field in FIELDS if field.get("required", False)]
        missing_fields = [field for field in required_fields if not data.get(field)]
        
        if missing_fields:
            logger.warning(f"Missing required fields: {missing_fields}")
            return False
        return True
    
    @staticmethod
    def build_replacements(data: Dict[str, Any]) -> Dict[str, str]:
        """Build replacement dictionary from form data"""
        replacements = {}
        
        # Process basic field replacements
        for field in FIELDS:
            field_name = field["name"]
            placeholder = field["placeholder"]
            field_value = data.get(field_name, "")
            
            if field.get("datatype") == "date":
                field_value = DocumentProcessor.convert_date_format(field_value)
            
            replacements[placeholder] = str(field_value)
        
        # Add computed fields
        replacements.update(FormDataProcessor._build_computed_replacements(replacements))
        
        return replacements
    
    @staticmethod
    def _build_computed_replacements(replacements: Dict[str, str]) -> Dict[str, str]:
        """Build computed replacement fields"""
        computed = {}
        
        # Build cause of action text
        cause_of_action = f"The cause of action for this claim petition arose on {replacements.get('(DATE1)', '')}, when the petitioner received a notice from the respondent. "
        
        # Add compensation amounts if present
        compensation_amounts = [
            ("(COA_AMNT3)", "The petitioner received an amount of {} as tower foot area compensation. "),
            ("(COA_AMNT1)", "The petitioner also received an amount of {} as tower foot area compensation. "),
            ("(COA_AMNT2)", "Thereafter the petitioner received an amount of {} as tower foot area compensation. ")
        ]
        
        for amount_key, template in compensation_amounts:
            amount = replacements.get(amount_key, "0")
            if amount and amount != "0":
                cause_of_action += template.format(amount)
        
        # Add jurisdiction clause
        village = replacements.get("(VILLAGE)", "")
        taluk = replacements.get("(TALUK)", "")
        cause_of_action += f"And there after continually at {village} Village in {taluk} Taluk which is within the jurisdiction of this Honourable Court."
        
        computed["(CAUSE_OF_ACTION)"] = cause_of_action
        
        # Handle ARES2 field
        ares2 = replacements.get("(ARES2)", "0")
        syno2 = replacements.get("(SYNO2)", "")
        if ares2 and ares2 != "0":
            computed["(ARES2)"] = f"and {ares2} in Sy.No. {syno2}"
        else:
            computed["(ARES2)"] = ""
        
        # Add other computed fields
        computed["(DISTRICT)"] = replacements.get("(DISTRICT)", "").upper()
        computed["(CURRENT_DATE)"] = DocumentProcessor.get_formatted_current_date()
        
        # Calculate total amount
        try:
            amount1 = int(replacements.get("(AMNT1)", 0) or 0)
            amount2 = int(replacements.get("(AMNT2)", 0) or 0)
            amount3 = int(replacements.get("(AMNT3)", 0) or 0)
            computed["(TOTAL_AMOUNT)"] = str(amount1 + amount2 + amount3)
        except (ValueError, TypeError):
            computed["(TOTAL_AMOUNT)"] = "0"
            logger.warning("Failed to calculate total amount")
        
        return computed

def create_app(config: Optional[AppConfig] = None) -> Flask:
    """Application factory function"""
    if config is None:
        config = AppConfig()
    
    app = Flask(__name__)
    
    # Initialize S3 client
    try:
        s3_client = boto3.client('s3')
    except NoCredentialsError:
        logger.error("AWS credentials not found")
        raise
    
    # Initialize processors
    doc_processor = DocumentProcessor(s3_client, config.bucket_name)
    form_processor = FormDataProcessor()
    
    @app.route("/", methods=["GET", "POST"])
    def form():
        """Main form handler"""
        if request.method == "GET":
            return render_template("form.html", fields=FIELDS)
        
        # Process POST request
        try:
            form_data = request.form.to_dict()
            
            # Validate form data
            if not form_processor.validate_form_data(form_data):
                abort(400, description="Missing required form fields")
            
            # Build replacements
            replacements = form_processor.build_replacements(form_data)
            
            # Handle petitioner address
            if request.form.get('petitioner_address_checker') == 'on':
                village = replacements.get("(VILLAGE)", "")
                taluk = replacements.get("(TALUK)", "")
                district = replacements.get("(DISTRICT)", "")
                pincode = replacements.get("(PINCODE)", "")
                replacements["(PETITIONER_ADDRESS)"] = f"{village} Village, {taluk} Taluk, {district} District. PIN -{pincode}"
            else:
                replacements["(PETITIONER_ADDRESS)"] = ""
            
            # Generate output filename and path
            output_filename = f"{doc_processor.get_custom_datetime_format()}_output.docx"
            output_path = f"{config.output_prefix}{output_filename}"
            
            # Process document
            if not doc_processor.process_docx(config.template_file, replacements, output_path):
                abort(500, description="Document processing failed")
            
            # Serve file
            return serve_s3_file_as_attachment(s3_client, config.bucket_name, output_path, output_filename)
            
        except Exception as e:
            logger.error(f"Form processing error: {e}")
            abort(500, description="Internal server error")
    
    @app.route("/download-document/<doc_type>", methods=["POST"])
    def download_document(doc_type):
        """Handle document download"""
        try:
            form_data = request.form.to_dict()
            
            # Validate form data
            if not form_processor.validate_form_data(form_data):
                abort(400, description="Missing required form fields")
            
            replacements = form_processor.build_replacements(form_data)
            
            # Handle petitioner address
            if request.form.get('petitioner_address_checker') == 'on':
                village = replacements.get("(VILLAGE)", "")
                taluk = replacements.get("(TALUK)", "")
                district = replacements.get("(DISTRICT)", "")
                pincode = replacements.get("(PINCODE)", "")
                replacements["(PETITIONER_ADDRESS)"] = f"{village} Village, {taluk} Taluk, {district} District. PIN -{pincode}"
            else:
                replacements["(PETITIONER_ADDRESS)"] = ""
            
            # Generate output filename and path for document
            output_filename = f"{doc_processor.get_custom_datetime_format()}_{doc_type}_output.docx"
            output_path = f"{config.output_prefix}{output_filename}"
            
            print("-----------------------")
            print(config.templates[doc_type])
            print("-----------------------")
            
            # Process document
            if not doc_processor.process_docx(config.templates[doc_type], replacements, output_path):
                abort(500, description="Document processing failed")
            
            # Serve file
            return serve_s3_file_as_attachment(s3_client, config.bucket_name, output_path, output_filename)
            
        except Exception as e:
            logger.error(f"Document processing error: {e}")
            abort(500, description="Internal server error")
    
    @app.errorhandler(400)
    def bad_request(error):
        return render_template('error.html', error="Bad Request", message=str(error.description)), 400
    
    @app.errorhandler(500)
    def internal_error(error):
        return render_template('error.html', error="Internal Server Error", message="Something went wrong"), 500
    
    return app

def main():
    """Main application entry point"""
    config = AppConfig(
        debug=os.getenv('FLASK_DEBUG', 'False').lower() == 'true',
        host=os.getenv('FLASK_HOST', '0.0.0.0'),
        port=int(os.getenv('FLASK_PORT', 5000))
    )
    
    app = create_app(config)
    app.run(host=config.host)

if __name__ == '__main__':
    main()