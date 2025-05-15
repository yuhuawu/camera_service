"""
This script captures frames from a video stream (RTSP or file) and puts them into a queue.
It uses OpenCV to read the video stream and a separate thread to handle the reading process.
The main thread processes the frames from the queue.
The script is designed to handle reconnections and errors gracefully.

The opencv2.videocapture().read() will cause a blocking read, 
but I still confused why using it in a sperated thread could make the work thread(reading the frame) detect stop_event timely compared with only one thread.

"""

import queue
import cv2
import logging
import threading

RECONNECT_DELAY_SECONDS = 10

from utils.subprocess_log import setup_logging, release_logging_handlers

def frame_reader_thread_func(live_stream_url: str, 
                             frame_queue: queue.Queue, 
                             stop_event_reader: threading.Event, 
                             logger_reader: logging.Logger, 
                             sample_rate: int): #sample rate defines how many frames per second to insert into the queue
    """
    Reads frames from the video stream and puts them into a queue.
    Runs in a separate thread.
    the stop_event_reader is used to signal the thread to stop, set by the main thread.
    """
    cap_reader = None
    logger_reader.info("[FrameReader] Thread started.")
    consecutive_read_errors = 0
    max_consecutive_read_errors = 5 # Adjust as needed

    sample_gap = 1.0 / sample_rate if sample_rate > 0 else 0.0
    logger_reader.info(f"[FrameReader] Sample rate: {sample_rate} fps, sample gap: {sample_gap:.2f}s")
    
    last_frame_time = None

    while not stop_event_reader.is_set():
        try:
            if cap_reader is None or not cap_reader.isOpened():
                logger_reader.info(f"[FrameReader] Opening video stream: {live_stream_url}")
                cap_reader = cv2.VideoCapture(live_stream_url, cv2.CAP_FFMPEG)
                if not cap_reader.isOpened():
                    logger_reader.warning(f"[FrameReader] Could not open video stream. Retrying in {RECONNECT_DELAY_SECONDS}s...")
                    if stop_event_reader.wait(timeout=RECONNECT_DELAY_SECONDS):
                        break
                    continue
                logger_reader.info("[FrameReader] Video stream opened successfully.")
                consecutive_read_errors = 0

            ret, frame = cap_reader.read()

            if not ret:
                consecutive_read_errors += 1
                logger_reader.error(f"[FrameReader] Error reading frame (ret=False). Error count: {consecutive_read_errors}")
                if cap_reader:
                    cap_reader.release()
                cap_reader = None
                sleep_time = RECONNECT_DELAY_SECONDS * 2 if consecutive_read_errors >= max_consecutive_read_errors else RECONNECT_DELAY_SECONDS /2 
                logger_reader.info(f"[FrameReader] Waiting {sleep_time}s before retrying...")
                if stop_event_reader.wait(timeout=sleep_time):
                    logger_reader.info("[FrameReader] Stop event received during read error wait.") 
                    break
                continue
            
            consecutive_read_errors = 0 # Reset on successful read
            current_time = time.time()
            if last_frame_time is None:
                last_frame_time = current_time
            time_diff = current_time - last_frame_time
            if time_diff < sample_gap:
                logger_reader.debug(f"[FrameReader] Frame skipped due to sample rate. Time since last frame: {time_diff:.2f}s")
                continue
            
            last_frame_time = current_time
             
            # Put frame into the queue, discard old one if queue is full (latest frame)
            try:
                # Non-blocking clear of the queue
                while not frame_queue.empty():
                    try:
                        frame_queue.get_nowait()
                    except queue.Empty:
                        break # Should be rare with maxsize=1
                logger_reader.debug(f"[FrameReader] Frame read successfully. Queue size before put: {frame_queue.qsize()}")
                frame_queue.put(frame, timeout=0.5) # Small timeout to prevent indefinite block
            except queue.Full:
                logger_reader.warning("[FrameReader] Frame queue was full after attempting to clear. Skipping frame.")
            except Exception as e_q:
                logger_reader.error(f"[FrameReader] Error putting frame to queue: {e_q}")

        except cv2.error as cv_err:
            logger_reader.error(f"[FrameReader] OpenCV error in reader thread: {cv_err}")
            if stop_event_reader.wait(timeout=RECONNECT_DELAY_SECONDS): 
                break
        except Exception as e:
            logger_reader.error(f"[FrameReader] Unexpected error in reader thread: {e}", exc_info=True)
            if stop_event_reader.wait(timeout=RECONNECT_DELAY_SECONDS): 
                break
        finally:
            if cap_reader and not cap_reader.isOpened():
                logger_reader.warning("[FrameReader] Video stream closed or not opened. Releasing capture.")
                cap_reader.release()
                cap_reader = None
                
    if cap_reader:
        cap_reader.release()
    logger_reader.info("[FrameReader] Thread stopped.")
    
from dotenv import load_dotenv
import os

import time    
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

    frame_queue = queue.Queue(maxsize=1)
    stop_event = threading.Event()# Adjust size as needed

    #for debug, rtsp = "recordings/full.mp4"
    rtsp_url = "recordings/full.mp4"    
    
    logger, fh = setup_logging(log_filename_prefix="capture_thread", logging_level=logging.DEBUG)
    
    reader_thread = threading.Thread(
        target=frame_reader_thread_func,
        args=(rtsp_url, frame_queue, stop_event, logger), # Pass the main stop_event
        name="FrameReaderThread"
    )
    reader_thread.daemon = True # So it exits if the main process exits unexpectedly
    reader_thread.start()
    logger.info("[MotionDetectionProcess] Frame reader thread started.")
    
    frame_cnt = 0
    
    while True:
        try:
            frame_queue.get(timeout=1.0) # Wait for a frame
            frame_cnt += 1                
        except queue.Empty:
            logger.debug("[MotionDetectionProcess] No frames in queue.")
            time.sleep(0.1) # Sleep briefly to avoid busy waiting
        except KeyboardInterrupt:
            logger.info("[MotionDetectionProcess] Keyboard interrupt received, stopping.")
            stop_event.set()
            break
        except Exception as e:
            logger.error(f"[MotionDetectionProcess] Error processing frame: {e}")
    # wait for the reader thread to finish
    if reader_thread.is_alive():
        logger.info("[MotionDetectionProcess] Waiting for frame reader thread to finish.")
        reader_thread.join(timeout=5)
        if reader_thread.is_alive():
            logger.warning("[MotionDetectionProcess] Frame reader thread did not finish in time.")
    else:
        logger.info("[MotionDetectionProcess] Frame reader thread has finished.")
    logger.info(f"[MotionDetectionProcess] Stopping main process. with: {frame_cnt} frames")
    release_logging_handlers(logger, fh)

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
    main()