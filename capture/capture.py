import cv2

def detect_motion(prev_frame, current_frame, threshold=5000):
    if prev_frame is None or current_frame is None:
        return False
    # Convert frames to grayscale
    prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
    curr_gray = cv2.cvtColor(current_frame, cv2.COLOR_BGR2GRAY)
    # Blur to reduce noise
    prev_gray = cv2.GaussianBlur(prev_gray, (21, 21), 0)
    curr_gray = cv2.GaussianBlur(curr_gray, (21, 21), 0)
    # Frame difference
    frame_delta = cv2.absdiff(prev_gray, curr_gray)
    thresh = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)[1]
    # Dilate for filling in holes
    thresh = cv2.dilate(thresh, None, iterations=2)
    # Find contours (areas with change)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    motion = False
    for c in contours:
        if cv2.contourArea(c) > threshold:
            motion = True
            break
    return motion