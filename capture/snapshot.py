import logging
import cv2

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

def test_select_snapshot():
    """
    Test the select_snapshot function.
    """
    src_path = "../test.mp4"  # Replace with your test video path
    dest_path = "snapshot.jpg"  # Replace with your desired snapshot path
    result = select_snapshot(src_path, dest_path)
    if result:
        logging.info("Snapshot selection test passed.")
    else:
        logging.error("Snapshot selection test failed.")