from flask import Flask, render_template, request, send_file, make_response
import tempfile
import os

def serve_s3_file_as_attachment(s3, bucket_name, s3_path, download_filename=None):
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
