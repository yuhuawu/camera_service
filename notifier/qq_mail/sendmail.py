import os
import logging
import smtplib

from email.message import EmailMessage

def send_qq_mail(msg: EmailMessage) -> bool:
    """
    Send an email using QQ Mail.
    
    :param sender: Sender's QQ email address
    :param receiver: Receiver's email address
    :param code: QQ Mail authorization code
    :param subject: Subject of the email
    :param body: Body of the email
    """
    
    sender = os.getenv("QQ_MAIL_SENDER")
    receiver = os.getenv("MAIL_RECEIVER")
    code = os.getenv("QQ_MAIL_CODE") 
    
    # Create the email message

    msg['From'] = sender
    msg['To'] = receiver

    # Attach the body to the email
    #msg.attach(MIMEText(body, 'plain'))

    # Connect to the SMTP server
    
    server =  smtplib.SMTP_SSL('smtp.qq.com', 465)
    #server.set_debuglevel(1) 
    #server.ehlo()
    #server.starttls()
    #server.ehlo()
    try:
        server.login(sender, code)
        server.sendmail(sender, [receiver], msg.as_string())
    except smtplib.SMTPAuthenticationError as e:
        logging.error(f"SMTP Authentication Error: {e}")
        return False
    except smtplib.SMTPException as e:
        logging.error(f"SMTP Error: {e}")
        return False
    except Exception as e:
        logging.error(f"Unexpected Error: {e}")
        return False
    finally:
        server.quit()
    
    return True


from dotenv import load_dotenv
def test_send_mail(): 
    is_successuful = send_qq_mail("Test Subject", "Test Body")
    if not is_successuful:
        logging.error("Failed to send email.")
    else:
        logging.info("Email sent successfully.")
    
def test_send_html_mail_with_attachement():
    subject = "Test Subject"
    body = "<h1>This is a test email</h1><p>With HTML content</p>"
    
    msg = EmailMessage()
    msg['Subject'] = subject
    msg.set_content(body, subtype='html')

    is_successuful = send_qq_mail(msg)
    if not is_successuful:
        logging.error("Failed to send email.")
    else:
        logging.info("Email sent successfully.")
  
from email.utils import make_msgid  
        
def test_send_html_mail_with_image_inline(): 
    msg = EmailMessage()
    
    subject = "Test Subject for HTML Email with Image"
    text_body = "This is a test email With HTML content and an image."
    
    msg['Subject'] = subject
    msg.set_content(text_body)
    
    img_cid = make_msgid()
    img_cid_strip = img_cid[1:-1]  # Remove angle brackets
    
    html_body = f"""
    <html>
    <body>
        <h1>This is a test email</h1>
        <p>With HTML content and an image.</p>
        <img src="cid:{img_cid_strip}" alt="Test Image.jpg">
    </body>
    </html>
    """    
    msg.add_alternative(html_body, subtype='html')
    
    # Attach an image
    with open('penguin.jpg', 'rb') as img: 
        img_data = img.read()
        msg.get_payload()[1].add_related(img_data, 'image', 'jpeg', cid=img_cid)
        msg.add_attachment(img_data, maintype='image', subtype='jpeg', filename='Test Image.jpg')


    is_successuful = send_qq_mail(msg)
    if not is_successuful:
        logging.error("Failed to send email.")
    else:
        logging.info("Email sent successfully.")

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", '.env')
    load_dotenv(env_path, interpolate=True, override=True, verbose=True)
    
    test_send_html_mail_with_image_inline()