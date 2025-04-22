from flask import Flask, render_template, request, send_file, make_response
from docx import Document
from datetime import datetime
import os
import tempfile
import io
import boto3 
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

s3 = boto3.client('s3')
bucket_name = "efiling-store"

def get_custom_datetime_format():
    return datetime.now().strftime("%d_%m_%YT%H_%M_%S")

def get_formatted_current_date():
    def get_ordinal_suffix(day):
        if 11 <= day <= 13:
            return 'th'
        return {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
    
    now = datetime.now()
    day = now.day
    suffix = get_ordinal_suffix(day)
    return f"{day}{suffix} {now.strftime('%B, %Y')}"

def convert_date_format(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return date_str

def process_docx(template_path, replacements, output_path):
    doc = Document(template_path)

    # Replace text in paragraphs
    for paragraph in doc.paragraphs:
        for old_text, new_text in replacements.items():
            if old_text in paragraph.text:
                paragraph.text = paragraph.text.replace(old_text, new_text)

    # Replace text in tables
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for old_text, new_text in replacements.items():
                    if old_text in cell.text:
                        cell.text = cell.text.replace(old_text, new_text)

    # Save to an in-memory buffer
    output_stream = io.BytesIO()
    doc.save(output_stream)
    output_stream.seek(0)

    # Upload the updated document to S3
    s3.upload_fileobj(output_stream, bucket_name, output_path)

def serve_s3_file_as_attachment(s3_path, download_filename=None):
    """
    Download a file from S3 and serve it as an attachment to the user.
    
    Args:
        s3_path (str): Path to the file in S3, without leading slash
        download_filename (str, optional): Filename to use for the download.
            If not provided, uses the filename from s3_path.
    
    Returns:
        Flask response object with file attachment
    """
    
    # Use the provided filename or extract from s3_path
    if download_filename is None:
        download_filename = os.path.basename(s3_path)
    
    # Create a temporary file to store the downloaded document
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(download_filename)[1]) as temp_file:
        temp_path = temp_file.name
    
    # Download the file from S3
    s3.download_file(bucket_name, s3_path, temp_path)
    
    # Determine MIME type based on file extension
    mime_types = {
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        '.pdf': 'application/pdf',
        '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        '.csv': 'text/csv',
        '.txt': 'text/plain',
        # Add more MIME types as needed
    }
    file_ext = os.path.splitext(download_filename)[1].lower()
    mime_type = mime_types.get(file_ext, 'application/octet-stream')
    
    # Send the file to the user as an attachment
    response = make_response(send_file(
        temp_path,
        mimetype=mime_type,
        as_attachment=True,
        download_name=download_filename
    ))
    
    # Clean up the temporary file after the response is sent
    @response.call_on_close
    def cleanup():
        if os.path.exists(temp_path):
            os.remove(temp_path)
    
    return response


@app.route("/", methods=["GET", "POST"])
def form():
    
    FIELDS = [
        {"name": "district", "label": "District", "placeholder": "(DISTRICT)", "datatype": "text"},
        {"name": "petitioner", "label": "Petitioner", "placeholder": "(PETITIONER)", "datatype": "text"},
        {"name": "petitioner_age", "label": "Petitioner Age", "placeholder": "(PETITIONER_AGE)", "datatype": "number"},
        {"name": "petitioner_details", "label": "Other Petitioner Details", "placeholder": "(PETITIONER_DETAILS)", "datatype": "text"},
        {"name": "advocate", "label": "Advocate", "placeholder": "(ADVOCATE)", "datatype": "text"},
        {"name": "village", "label": "Village", "placeholder": "(VILLAGE)", "datatype": "text"},
        {"name": "taluk", "label": "Taluk", "placeholder": "(TALUK)", "datatype": "text"},
        {"name": "town", "label": "Town", "placeholder": "(TOWN)", "datatype": "text"},
        {"name": "sof_p1_fdr_loc", "label": "Double Circuit Feeder Location", "placeholder": "(Double_Circuit_Feeder_Location)", "datatype": "text"},
        {"name": "sof_p5_adj_loc", "label": "Adjacent Property", "placeholder": "(ADJ_LOC)", "datatype": "text"},
        {"name": "sof_p5_market_value", "label": "Market Value Per Cent", "placeholder": "(MARKET_VALUE)", "datatype": "number"},
        {"name": "sof_p7_balance_cents", "label": "Balance Cents (Nominal Land)", "placeholder": "(CENTS_BALANCE)", "datatype": "number"},
        {"name": "sof_p8_date1", "label": "Cause of Action Date", "placeholder": "(DATE1)", "datatype": "date"},
        {"name": "sof_p8_date2", "label": "Tower Footage Compensation Date", "placeholder": "(DATE2)", "datatype": "date"},
        {"name": "sof_p8_date3", "label": "Tree Compensation Date", "placeholder": "(DATE3)", "datatype": "date"},
        {"name": "ccp_amnt1", "label": "Compensation for Diminution", "placeholder": "(AMNT1)", "datatype": "number"},
        {"name": "ccp_amnt2", "label": "Compensation for Tower Footage", "placeholder": "(AMNT2)", "datatype": "number"},
        {"name": "ccp_amnt3", "label": "Compensation for Trees Cut", "placeholder": "(AMNT3)", "datatype": "number"},
        {"name": "ttl_amt", "label": "Total Evaluation Amount", "placeholder": "(TOTAL_AMOUNT)", "datatype": "number"},
        {"name": "tax_rcpt_date4", "label": "Basic Tax Receipt Date", "placeholder": "(DATE4)", "datatype": "date"},
    ]


    if request.method == "POST":
        data = request.form.to_dict()

        replacements = {
            field["placeholder"]: (
                convert_date_format(data.get(field["name"])) if field.get("datatype") == "date" else data.get(field["name"], "")
            )
            for field in FIELDS
        }
        replacements["(CURRENT_DATE)"] = get_formatted_current_date()

        # print(replacements)
        output_filename = f"{get_custom_datetime_format()}_output.docx"
        output_path = "/output/"+output_filename

        process_docx("template.docx", replacements, output_path)
        
        return serve_s3_file_as_attachment(output_path, output_filename)

    return render_template("form.html", fields=FIELDS)

if __name__ == '__main__':
    app.run(host='0.0.0.0')