import logging
import os
import time
from typing import NamedTuple
import cv2
import multiprocessing

from multiprocessing.synchronize import Event as EventType
from datetime import datetime

from enum import Enum
from dataclasses import dataclass

from utils.subprocess_log import setup_logging, release_logging_handlers
import sys

DETECTION_FPS = 5
DETECTION_RESIZE_DIM = (640, 480) # Resize for faster processing

DIFF_RATIO_THREASHOLD = 0.05 # Threshold for same frame detection 0.5%
MIN_MOTION_AREA = 5000 # Minimum area for motion detection

class EventType(Enum):
    MOTION = 0
    NO_FRAME = 1

class MotionEvent(NamedTuple):
    event_type: EventType   
    start_timestamp: str
    end_timestamp: str
    snapshot_img: str
    
class CurrentState(Enum):
    STATIC = 0
    MOTION = 1

@dataclass
class DetectStatistics():
    # log the statistics every 10 minutes or exit the process
    cap_connect_count: int
    total_frames: int
    check_frames: int
    ignored_frames: int
    
    motion_frames: int
    static_frames: int
    
    motion_event_count: int
   

def load_base_frame_img(base_frame_img_path):
    """
    Load the base frame image from the specified path.
    """
    if not os.path.exists(base_frame_img_path):
        raise FileNotFoundError(f"Base frame image not found at {base_frame_img_path}")
    
    base_frame_img = cv2.imread(base_frame_img_path)
    if base_frame_img is None:
        raise ValueError(f"Failed to load base frame image from {base_frame_img_path}")
    
    # Resize the base frame image to the same dimensions as the detection resize dimension
    if DETECTION_RESIZE_DIM:
        base_frame_img = cv2.resize(base_frame_img, DETECTION_RESIZE_DIM, interpolation=cv2.INTER_LINEAR)
    # Convert to grayscale for comparison
    base_frame_img = cv2.cvtColor(base_frame_img, cv2.COLOR_BGR2GRAY)
    return base_frame_img


def diff_ratio_between_two_frames(base_gray_frame, current_gray_frame, logger) -> float:
    """
    Check if the current frame are the two gray frame are the same.
    """
    if base_gray_frame.shape != current_gray_frame.shape:
        logger.warning(f"[is_same_frame] Frame shapes do not match: {base_gray_frame.shape} vs {current_gray_frame.shape}")
        return False
    
    # Calculate the absolute difference between the two frames
    frame_diff = cv2.absdiff(base_gray_frame, current_gray_frame)
    # Threshold the difference to get a binary image
    _, thresh = cv2.threshold(frame_diff, 25, 255, cv2.THRESH_BINARY)
    # Count the number of non-zero pixels in the thresholded image
    non_zero_count = cv2.countNonZero(thresh)
    # If the number of non-zero pixels is less than a threshold, consider the frames the same
    #logger.info(f"[is_same_frame] Non-zero pixel count: {non_zero_count}")
    total_pixels = base_gray_frame.size
    #logger.info(f"[is_same_frame] Total pixels: {total_pixels}")
    #total_pixels = base_gray_frame.shape[0] * base_gray_frame.shape[1]
    #logger.info(f"[is_same_frame] Total pixels: {total_pixels}")
    # Calculate the ratio of non-zero pixels to total pixels
    diff_ratio = non_zero_count * 1.0 / total_pixels  
    return diff_ratio


def detect_motion(pre_gray_frame, current_gray_frame) -> bool:
    """
    try to detect motion between the two frames.
    """
    if pre_gray_frame is None or current_gray_frame is None:
        return False
    # Convert to grayscale and blur
    prev_gray = cv2.cvtColor(pre_gray_frame, cv2.COLOR_BGR2GRAY)
    curr_gray = cv2.cvtColor(current_gray_frame, cv2.COLOR_BGR2GRAY)
   
    # Blur the images to reduce noise
    prev_gray = cv2.GaussianBlur(pre_gray_frame, (21, 21), 0)
    curr_gray = cv2.GaussianBlur(current_gray_frame, (21, 21), 0)
    # Frame difference
    frame_delta = cv2.absdiff(prev_gray, curr_gray)
    thresh = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)[1]
    # Dilate for filling in holes
    thresh = cv2.dilate(thresh, None, iterations=2)
    # Find contours (areas with change)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in contours:
        if cv2.contourArea(c) > MIN_MOTION_AREA:
            return True
    return False


    

"""
logic:
- 

one variables to store the comparision between frames
variable 1: is_like_base_frame

one variable to store current state: 
state 1: static
state 2: motion 
 
 static ---is_like_base_frame = false ---> motion -+
    ^                                              |
    |                                              |
    +------is_like_base_frame = true---------------+
    
if is_like_base_frame: # most of the time
    if state is static: # most of the time
        do nothing, just continue
    else: # if state is motion
        set state to static 

if has_motion_detected:
    if state is static:
        set state to motion
    if state is motion:

"""

import threading
import queue
from capture.capture_to_frame import frame_reader_thread_func

def log_statistics(statistics: DetectStatistics, logger):
    """
    Log the statistics every 10 minutes or exit the process.
    """
    logger.info(f"[Statistics] Total frames: {statistics.total_frames}")
    logger.info(f"[Statistics] Check frames: {statistics.check_frames}")
    logger.info(f"[Statistics] Ignored frames: {statistics.ignored_frames}")
    logger.info(f"[Statistics] Motion frames: {statistics.motion_frames}")
    logger.info(f"[Statistics] Static frames: {statistics.static_frames}")
    logger.info(f"[Statistics] Motion event count: {statistics.motion_event_count}")


def motion_detection_process(motion_event_queue: multiprocessing.Queue, 
                             stop_event: EventType,
                             live_stream_url: str,
                             base_frame_img_path: str,
                             ):
    logger, fh = setup_logging("motion_detection", logging.DEBUG)
    logger.info("[MotionDetectionProcess] Starting motion detection process...")
    
    cap = None
    gray_frame = None
    
    is_like_base_frame = False
    state = CurrentState.STATIC
    
    motion_start_time = None
    motion_end_time = None
    
    last_dump_statistics_time = None
    
    statistics = DetectStatistics(
        cap_connect_count=0,
        total_frames=0,
        check_frames=0,
        ignored_frames=0,
        motion_frames=0,
        static_frames=0,
        motion_event_count=0
    )
    
    base_gray_frame = load_base_frame_img(base_frame_img_path)
    if base_gray_frame is None:
        logger.error(f"[MotionDetectionProcess] Error: Base frame image not found at {base_frame_img_path}.")
        raise FileNotFoundError(f"Base frame image not found at {base_frame_img_path}")

    # start the capture to frame thread
    reader_thread_stop_event = threading.Event()
    frame_queue = queue.Queue(maxsize=1)
    reader_thread = threading.Thread(
        target=frame_reader_thread_func,
        args=(live_stream_url, frame_queue, reader_thread_stop_event, logger, DETECTION_FPS), # Pass the main stop_event
        name="FrameReaderThread"
    )
    reader_thread.daemon = True # So it exits if the main process exits unexpectedly
    reader_thread.start()
    logger.info("[MotionDetectionProcess] Frame reader thread started.")

    max_diff_ratio = 0.0
    snapshot_frame = None

    try:
        while not stop_event.is_set():
            try:
                frame = frame_queue.get(timeout=1) # Wait for a frame            
           
                # now process the frame
                current_time = time.time()
                statistics.total_frames += 1
                    
                if last_dump_statistics_time is None:
                    last_dump_statistics_time = current_time
                if current_time - last_dump_statistics_time > 60: # 1 minute for debug.
                    log_statistics(statistics, logger)
                    last_dump_statistics_time = current_time
                    
                statistics.check_frames += 1
                # 2. Resize for faster processing
                if DETECTION_RESIZE_DIM:
                    resized_frame = cv2.resize(frame, DETECTION_RESIZE_DIM, interpolation=cv2.INTER_LINEAR)
                else:
                    resized_frame = frame.copy() # if no resize, work on a copy

                gray_frame = cv2.cvtColor(resized_frame, cv2.COLOR_BGR2GRAY)
                
                # 3. Check if the current frame is the same as the base frame
                diff_ratio = diff_ratio_between_two_frames(base_gray_frame, gray_frame, logger)
                if diff_ratio > DIFF_RATIO_THREASHOLD:
                    is_like_base_frame = False
                else:
                    is_like_base_frame = True
                    
                if is_like_base_frame: 
                    statistics.static_frames += 1
                    if state == CurrentState.STATIC:
                        # If the state is already static, do nothing
                        logger.info("Frame is the same as base frame. Skipping motion detection.")
                    else:
                        # If the state is motion, set it to static
                        state = CurrentState.STATIC
                        logger.info("Frame is the same as base frame. Setting state to STATIC, and put motion event to queue.")
                        motion_end_time = datetime.fromtimestamp(current_time)
                        # try to dump frame to image file
                        snapshot_img_name = ''
                        if snapshot_frame is not None:
                            # save the frame to a file
                            snapshot_img_name = f"motion_{motion_start_time.strftime('%Y%m%d_%H%M%S')}.jpg"
                            snapshot_img_path = os.path.join(os.path.dirname(__file__), "..", "snapshots", snapshot_img_name)
                            cv2.imwrite(snapshot_img_path, snapshot_frame)
                            logger.info(f"[MotionDetectionProcess] Saved motion frame to {snapshot_img_path}")                           
                            snapshot_frame = None
                            max_diff_ratio = 0.0
                        # now add start end time to the queue
                        if motion_start_time:
                            try:
                                motion_event_queue.put(MotionEvent(
                                    EventType.MOTION,
                                    start_timestamp=motion_start_time.strftime("%Y-%m-%d %H:%M:%S"), 
                                    end_timestamp=motion_end_time.strftime("%Y-%m-%d %H:%M:%S"), 
                                    snapshot_img=snapshot_img_name), timeout=0.5)
                                statistics.motion_event_count += 1
                            except multiprocessing.queues.Full:
                                print("Motion event queue full. Dropping event.")
                            motion_start_time = None
                            motion_end_time = None
                else:
                    if diff_ratio > max_diff_ratio:
                        logger.info(f"[MotionDetectionProcess] Frame diff ratio: {diff_ratio:.2f} > max diff ratio: {max_diff_ratio:.2f}. Saving frame.")
                        max_diff_ratio = diff_ratio
                        snapshot_frame = frame.copy()
                    statistics.motion_frames += 1
                    if state == CurrentState.STATIC:
                        # If the state is static, set it to motion
                        state = CurrentState.MOTION
                        logger.info("Frame is different from base frame. Setting state to MOTION.")
                        motion_start_time = datetime.fromtimestamp(current_time)
                    else:
                        # If the state is motion, do nothing, motion is under going
                        logger.info("Frame is different from base frame. Motion continues.")                  
            
            except queue.Empty: #for queue.get()
                logger.debug("[MotionDetectionProcess] No frames in queue.")
                # just add event to the queue. reset all the variables. 
                if state == CurrentState.STATIC:
                    # If the state is static, do nothing
                    logger.info("No frame in queue. Skipping motion detection.")
                    continue
                else:
                    # If the state is motion, set it to static
                    state = CurrentState.STATIC
                    logger.info("No frame in queue. Setting state to STATIC, and put motion event to queue.")
                    motion_end_time = datetime.now()
                    # now add start end time to the queue
                    snapshot_img_name = ''
                    if snapshot_frame is not None:
                        # save the frame to a file
                        snapshot_img_name = f"motion_{motion_start_time.strftime('%Y%m%d_%H%M%S')}.jpg"
                        snapshot_img_path = os.path.join(os.path.dirname(__file__), "..", "snapshots", snapshot_img_name)
                        cv2.imwrite(snapshot_img_path, snapshot_frame)
                        logger.info(f"[MotionDetectionProcess] Saved motion frame to {snapshot_img_path}")                           
                        snapshot_frame = None
                        max_diff_ratio = 0.0
                    if motion_start_time:
                        try:
                            motion_event_queue.put(MotionEvent(
                                EventType.NO_FRAME,
                                start_timestamp=motion_start_time.strftime("%Y-%m-%d %H:%M:%S"), 
                                end_timestamp=motion_end_time.strftime("%Y-%m-%d %H:%M:%S"),
                                snapshot_img=snapshot_img_name), timeout=0.5)
                            statistics.motion_event_count += 1
                        except multiprocessing.queues.Full:
                            print("Motion event queue full. Dropping event.")
                        motion_start_time = None
                        motion_end_time = None
                    continue            
            except KeyboardInterrupt:
                logger.info("[MotionDetectionProcess] KeyboardInterrupt received. Exiting...")
                stop_event.set()
                break
            except Exception as e:
                # for error we don't expect, we break, quit the process 
                logger.error(f"[MotionDetectionProcess] Error getting frame from queue: {e}")
                stop_event.set()             
                break
 
    
    finally:
        logger.info("[MotionDetectionProcess] Entering finally block for cleanup...")
        
        logger.info("[MotionDetectionProcess] Signaling frame reader thread to stop...")
        reader_thread_stop_event.set()
        if reader_thread.is_alive():
            reader_thread.join(timeout=5.0) 
            if reader_thread.is_alive():
                logger.warning("[MotionDetectionProcess] Frame reader thread did not join in time.")
        else:
            logger.info("[MotionDetectionProcess] Frame reader thread was already stopped.")
            
        log_statistics(statistics, logger)
        logger.info("[MotionDetectionProcess] Process finished cleanup.")
        release_logging_handlers(logger, fh)
        sys.exit(0) # Exit the process
    
from dotenv import load_dotenv

def main():
    env_file = os.path.join(os.path.dirname(__file__), "..", ".env")
    load_dotenv(env_file, override=True, verbose=True, interpolate=True)    

    rtsp_urls_env = os.getenv("RTSP_URLS")
    if not rtsp_urls_env:
        logging.error("RTSP_URLS environment variable is not set.")
        raise ValueError("RTSP_URLS is not set.")
    try:
        rtsp_urls_obj = eval(rtsp_urls_env) # Caution with eval; consider json.loads if format allows
        if not isinstance(rtsp_urls_obj, list) or not rtsp_urls_obj or not isinstance(rtsp_urls_obj[0], str):
            raise ValueError("RTSP_URLS should be a non-empty list of strings.")
        rtsp_url = rtsp_urls_obj[0]
    except Exception as e:
        logging.error(f"Error parsing RTSP_URLS: {e}. Example: \"['rtsp://user:pass@host/stream']\"")
        raise

    base_frame_img_name = os.getenv("BASE_FRAME_IMAGE_PATH")
    if not base_frame_img_name:
        raise ValueError("BASE_FRAME_IMAGE_PATH is not set.")
    base_frame_img_path = os.path.join(os.path.dirname(__file__), "..", base_frame_img_name)
    if not os.path.exists(base_frame_img_path):
        raise ValueError(f"BASE_FRAME_IMG_PATH: {base_frame_img_path} does not exist.")

    snapshot_dirname = os.getenv("SNAPSHOT_DIR")
    if not snapshot_dirname:
        raise ValueError("SNAPSHOT_DIR is not set.")
    snapshot_dir_path = os.path.join(os.path.dirname(__file__), "..", snapshot_dirname)
    if not os.path.exists(snapshot_dir_path):
        os.makedirs(snapshot_dir_path)
        logging.info(f"Created snapshot directory: {snapshot_dir_path}")

    motion_event_queue = multiprocessing.Queue(maxsize=100)
    stop_event = multiprocessing.Event()# Adjust size as needed

    #for debug, rtsp = "recordings/full.mp4"
    #rtsp_url = "recordings/full.mp4"

    detect_process = multiprocessing.Process(
        target=motion_detection_process,
        args=(motion_event_queue, stop_event, rtsp_url, base_frame_img_path),
        name="MotionDetectionProcess"
    )
    
    detect_process.start()
    
    logging.info(f"[Main] Motion detection process started. PID: {detect_process.pid}")
    
    # try to get the motion event from the queue
    try:
        while True:
            if not motion_event_queue.empty():
                try:
                    event_type, motion_start_time, motion_end_time, snap_img_name = motion_event_queue.get(timeout=0.5)
                    logging.info(f"[Main] Motion: {event_type} detected from {motion_start_time} to {motion_end_time}, snapshot: {snap_img_name}")
                except multiprocessing.queues.Empty:
                    logging.info("[Main] No motion event in queue.")
            else:
                logging.info("[Main] No motion event in queue.")
            time.sleep(1) 
            # Check if the process is alive
            if not detect_process.is_alive():
                logging.info("[Main] Motion detection process is not alive. Exiting...")
                break
            logging.info(f"[Main] Motion detection process is alive. PID: {detect_process.pid}")
    except KeyboardInterrupt:
        logging.info("[Main] Received KeyboardInterrupt. Stopping motion detection process...")
    finally:
        logging.info("[Main] Stopping motion detection process...")
        stop_event.set()
        detect_process.join(timeout=10)
        logging.info("[Main] Motion detection process stopped.")
        if detect_process.is_alive():
            detect_process.terminate()
            detect_process.join()
            logging.info("[Main] Motion detection process terminated.")
        else:
            logging.info("[Main] Motion detection process already stopped.")      

if __name__ == "__main__":
    # Load environment variables
    
    # Set up logging
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(process)d - %(levelname)s - %(message)s')
    
    # Start the main async function
    main()  