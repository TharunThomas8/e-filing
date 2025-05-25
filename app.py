from flask import Flask, render_template, request, send_file, make_response
from docx import Document
from datetime import datetime
import os
import tempfile
import io
import boto3 
from dotenv import load_dotenv
from form_fields import FIELDS
from s3_bucketHandler import *

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

@app.route("/", methods=["GET", "POST"])
def form():

    if request.method == "POST":
        data = request.form.to_dict()

        replacements = {
            field["placeholder"]: (
                convert_date_format(data.get(field["name"])) if field.get("datatype") == "date" else data.get(field["name"], "")
            )
            for field in FIELDS
        }

        replacements["(CAUSE_OF_ACTION)"] = "The cause of action for this claim petition arose on " + replacements["(DATE1)"] + ", when the petitioner received a notice from the respondent. "
        if replacements["(COA_AMNT3)"]!= '0':
            replacements["(CAUSE_OF_ACTION)"]+=  "The petitioner received an amount of " + replacements["(COA_AMNT3)"] + " as tower foot area compensation. "
        if replacements["(COA_AMNT1)"]!= '0':
            replacements["(CAUSE_OF_ACTION)"]+=  "The petitioner also received an amount of " + replacements["(COA_AMNT1)"] + " as tower foot area compensation. "
        if replacements["(COA_AMNT2)"]!= '0':
            replacements["(CAUSE_OF_ACTION)"]+=  "Thereafter the petitioner received an amount of " + replacements["(COA_AMNT2)"] + " as tower foot area compensation. "
        
        if replacements["(ARES2)"]!=0:
            replacements["(ARES2)"] = "and " + replacements["(ARES2)"] + " in Sy.No. " + replacements["(SYNO2)"]
        
        replacements["(DISTRICT)"] = replacements["(DISTRICT)"].upper()
        replacements["(CURRENT_DATE)"] = get_formatted_current_date()
        replacements["(TOTAL_AMOUNT)"] = str(int(replacements["(AMNT1)"]) + int(replacements["(AMNT2)"]) + int(replacements["(AMNT3)"]))
        replacements["(CAUSE_OF_ACTION)"] += "And there after continually at " + replacements["(VILLAGE)"] + " Village in " + replacements["(TALUK)"] + " Taluk which is within the jurisdiction of this Honourable Court."
        
        if request.form.get('petitioner_address_checker') == 'on':
            replacements["(PETITIONER_ADDRESS)"] = replacements["(VILLAGE)"] + ' Village, ' + replacements["(TALUK)"] + ' Taluk, ' + replacements["(DISTRICT)"] + ' District. PIN -' + replacements["(PINCODE)"]
        else:
            replacements["(PETITIONER_ADDRESS)"] = ''
            

        # print(replacements)
        output_filename = f"{get_custom_datetime_format()}_output.docx"
        output_path = "/output/"+output_filename

        process_docx("template.docx", replacements, output_path)
        
        return serve_s3_file_as_attachment(s3, bucket_name, output_path, output_filename)

    return render_template("form.html", fields=FIELDS)

if __name__ == '__main__':
    app.run(host='0.0.0.0')