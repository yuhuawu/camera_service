import os
import logging
import smtplib
from email.mime.text import MIMEText


def send_qq_mail(sender, receiver, code, subject, body) -> bool:
    """
    Send an email using QQ Mail.
    
    :param sender: Sender's QQ email address
    :param receiver: Receiver's email address
    :param code: QQ Mail authorization code
    :param subject: Subject of the email
    :param body: Body of the email
    """
    # Create the email message
    msg  = MIMEText(body, 'plain', _charset='utf-8')

    msg['From'] = sender
    msg['To'] = receiver
    msg['Subject'] = subject

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
    logging.basicConfig(level=logging.DEBUG)
    
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", '.env')
    load_dotenv(env_path, interpolate=True, override=True, verbose=True)
   
    sender = os.getenv("QQ_MAIL_SENDER")
    receiver = os.getenv("MAIL_RECEIVER")
    code = os.getenv("QQ_MAIL_CODE")    

    is_successuful = send_qq_mail(sender, receiver, code, "Test Subject", "Test Body")
    if not is_successuful:
        logging.error("Failed to send email.")
    else:
        logging.info("Email sent successfully.")
    
    
if __name__ == "__main__":
    test_send_mail()