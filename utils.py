import logging
import cv2
import numpy as np

import os


def select_snapshot(src_path: str, dest_path: str) -> bool:
    """
    Select a snapshot from the video file and save it to the destination path.
    :param src_path: Path to the source video file
    :param dest_path: Path to save the snapshot image
    set first frame as base image
    compare other frames with base image
    select the frame with max difference
    """
    logging.info(f"[Snapshot] Selecting snapshot from {src_path} to {dest_path}")
    
    if not src_path or not os.path.exists(src_path):
        logging.error(f"File not found: {src_path}")
        return

    cap = cv2.VideoCapture(src_path)
    if not cap.isOpened():
        logging.error(f"Error: Unable to open the video file {src_path}.")
        return

    frames = []
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frames.append(frame)
    
    cap.release()

    if len(frames) == 0:
        logging.error(f"No frames found in the video file {src_path}.")
        return False
    
    diffs = [0] * len(frames)
    base_frame = frames[0]
    base_gray = cv2.cvtColor(base_frame, cv2.COLOR_BGR2GRAY)
    base_gray = cv2.GaussianBlur(base_gray, (21, 21), 0)

    
    for i in range(len(frames)):   
        if i == 0:
            continue
        # Convert frames to grayscale        
        curr_gray = cv2.cvtColor(frames[i], cv2.COLOR_BGR2GRAY)
        # Blur to reduce noise
        curr_gray = cv2.GaussianBlur(curr_gray, (21, 21), 0)
        # Frame difference
        frame_delta = cv2.absdiff(base_gray, curr_gray)
        diffs[i] = np.sum(frame_delta) 
        
    max_diff_index = np.argmax(diffs)
    logging.info(f"[Snapshot] Frame with max difference: {max_diff_index}, Difference: {diffs[max_diff_index]}")
    
    cv2.imwrite(dest_path, frames[max_diff_index])
    logging.info(f"[Snapshot] Snapshot saved to {dest_path}")
    return True

from email.message import EmailMessage
from email.utils import make_msgid  


def send_mail(title, directory, image_name) -> bool:
    """
    Send an email notification with the filename.
    :param title, ymd-hms
    :param directory, path to the image and video
    :param image_name, name of the image
    """
    from notifier.qq_mail.sendmail import send_qq_mail
    
    video_name = image_name.split(".")[0] + ".mp4"      
    subject = f"Motion Detected at - {title}"
    body = f"File saved as: {video_name}"
    img_path = os.path.join(directory, image_name)
    
    msg = EmailMessage()
    msg["Subject"] = subject
    msg.set_content(body)
    
    img_cid = make_msgid()
    img_cid_strip = img_cid[1:-1]  # Remove angle brackets
    html_body = f"""
    <html>
    <body>
        <h1>Motion Detected</h1>
        <p>File saved as: {video_name}</p>
        <img src="cid:{img_cid_strip}" alt="{image_name}">
    </body>
    </html>
    """    
    msg.add_alternative(html_body, subtype='html')
    
    with open(img_path, 'rb') as img:
        img_data = img.read()
        msg.get_payload()[1].add_related(img_data, 'image', 'jpeg', cid=img_cid)
        msg.add_attachment(img_data, maintype='image', subtype='jpeg', filename=image_name)
        
    try:
        is_successful = send_qq_mail(msg)
    except Exception as e:
        logging.error(f"Failed to send email: {e}")
        return False
    
    return is_successful

def test_select_snapshot():
    """
    Test the select_snapshot function.
    """
    src_path = "test.mp4"  # Replace with your test video path
    dest_path = "snapshot.jpg"  # Replace with your desired snapshot path
    result = select_snapshot(src_path, dest_path)
    if result:
        logging.info("Snapshot selection test passed.")
    else:
        logging.error("Snapshot selection test failed.")

def test_send_mail():
    """
    Test the send_mail function.
    """
    title = "Test Title"
    directory = "."  # Current directory
    image_name = "snapshot.jpg"  # Replace with your test image name
    result = send_mail(title, directory, image_name)
    if result:
        logging.info("Email sending test passed.")
    else:
        logging.error("Email sending test failed.")
        
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    #test_select_snapshot()
    test_send_mail()
