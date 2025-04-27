import cv2
import numpy as np
import datetime
import os
import logging
import shutil
import asyncio

MOTION_THRESHOLD = 5000
NO_MOTION_SECONDS = 5

from capture import detect_motion
from utils import send_mail
from utils import select_snapshot


async def process_vidoe_file(src_path: str, loop: asyncio.AbstractEventLoop):
    """
    Process the video file:
    1, move it to archive_dir year/month/date/timestamp.mp4.
    2, send a email to notify the user.
    :param src_path: Path to the source video file
    :param loop: Event loop for async processing
    """
    logging.info(f"[Async Handler] Processing video file: {src_path}")
            
    if not src_path or not os.path.exists(src_path):
        logging.error(f"File not found: {src_path}")
        return

    filename = os.path.basename(src_path)
    parts = filename.split("_")
    if  len(parts) < 3:
        logging.error(f"Invalid filename format: {filename}")
        return
        
    date_str = parts[1]
    time_str = parts[2].split(".")[0]
    
    year, month, day = date_str[0:4], date_str[4:6], date_str[6:8]
    archive_dir = os.getenv("ARCHIVE_DIR")
    directory = os.path.join(archive_dir, year, month, day)
    if not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)
    
    dest_name = parts[2]
    dest_path = os.path.join(directory, dest_name)
        
    try:
        await loop.run_in_executor(None, shutil.move, src_path, dest_path)
        logging.info(f"[Async Handler] Moved file: {f"{src_path}"} to archive: {dest_path}")
        
        image_name = f"{time_str}.jpg"
        ret = await loop.run_in_executor(None, select_snapshot, dest_path, os.path.join(directory, image_name))
        if ret:
            logging.info(f"[Async Handler] Snapshot taken successfully for file: {filename}")
        else:
            logging.error(f"[Async Handler] Failed to take snapshot for file: {filename}")
            image_name = None
        
        mail_ttile = date_str + "-" + time_str
        ret = await loop.run_in_executor(None, send_mail, mail_ttile, directory, image_name)
        if ret:
            logging.info(f"[Async Handler] Email sent successfully for file: {filename}")
        else:
            logging.error(f"[Async Handler] Failed to send email for file: {filename}")
            
    except Exception as e:
        logging.error(f"Error when handling file {src_path} with error: {e}")
        return
    
    logging.info(f"[Async Handler] Finished processing video file: {src_path}")
    
    
async def consumer(queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
    """
    Consume video files from the queue and process them.
    :param queue: Queue to consume video files from
    :param loop: Event loop for async processing
    """
    logging.info("[Async Handler] Waiting for video file to process...")

    while True:
        src_path = await queue.get()
        if src_path is None: # Sentinel value received
            logging.info("[Async Handler] Received sentinel value. Exiting consumer.")
            queue.task_done()
            break
        logging.info(f"[Async Handler] Processing video file: {src_path}")
        asyncio.create_task(process_vidoe_file(src_path, loop))
        #await process_vidoe_file(src_path, loop)
        queue.task_done() # Signal that this item has been processed   
    
    logging.info("[Async Handler] Video Consumer Finished.")


def video_stream_monitor(rtsp_url: str, output_dir: str, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
    """
    Produce video files to the queue.
    :param rtsp_url: RTSP URL to capture video from
    :param queue: Queue to produce video files to
    :param loop: Event loop for async processing
    """
    logging.info(f"[Video Stream Monitor Thread] Starting video stream monitor for URL: {rtsp_url}")
    cap = cv2.VideoCapture(rtsp_url)
    if not cap.isOpened():
        logging.error(f"Error: Unable to open the RTSP stream {rtsp_url}.")
        loop.call_soon_threadsafe(queue.put_nowait, None) # Send sentinel value to consumer
        return
    
    # Initialize variables
    prev_frame = None
    recording = False
    out = None
    last_motion_time = None
    current_recording_file = None
    fps = int(cap.get(cv2.CAP_PROP_FPS)) or 30
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    while True:
        #try:
            ret, frame = cap.read()
            if not ret:
                logging.error("[Video Stream Monitor Thread] Stream read error.")
                break
            
            # Make a copy for motion detection to avoid race conditions if needed elsewhere
            frame_copy_for_detection = frame.copy()
            motion_detected = detect_motion(prev_frame, frame_copy_for_detection, MOTION_THRESHOLD)
                        
            if motion_detected: # Motion detected, start recording if not recording:
                current_time = datetime.datetime.now()
                if not recording:   # Start recording
                    ts = current_time.strftime("%Y%m%d_%H%M%S")
                    video_filepath = os.path.join(output_dir, f"motion_{ts}.mp4")
                    current_recording_file = video_filepath
                    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                    out = cv2.VideoWriter(video_filepath, fourcc, fps, (width, height))
                    if not out.isOpened():
                        logging.error(f"[Video Stream Monitor Thread] Error: Unable to open video writer for {video_filepath}.")
                        recording = False
                        current_recording_file = None
                    else:
                        recording = True
                        logging.info(f"[Video Stream Monitor Thread] Motion detected. Recording started: {video_filepath}")
                last_motion_time = current_time
            
            if not motion_detected: #no motion detected 
                if recording and last_motion_time: #recording is in progress, then need to stop it after NO_MOTION_SECONDS
                    elapsed = (datetime.datetime.now() - last_motion_time).total_seconds()
                    if elapsed > NO_MOTION_SECONDS:
                        # Stop recording
                        logging.info(f"[Video Stream Monitor Thread] No motion detected for {NO_MOTION_SECONDS} seconds. Stopping recording.")
                        recording = False
                        if out is not None:
                            out.release()
                            out = None
                        if current_recording_file:
                            logging.info(f"[OpenCV Thread] Adding to queue: {current_recording_file}")
                            # Use call_soon_threadsafe because we are in a different thread
                            loop.call_soon_threadsafe(queue.put_nowait, current_recording_file)
                            current_recording_file = None # Reset after queuing
                        last_motion_time = None # Reset timer
                    
            if recording and out is not None and out.isOpened(): #now recording
                # Write the frame to the video file
                out.write(frame)
                        
            prev_frame = frame_copy_for_detection
            
            #cv2.imshow("RTSP Stream", frame)
            #key = cv2.waitKey(10)
            #if key != -1 and  key == ord('q'):
            #    logging.info(f"[Video Stream Monitor Thread] Key: {chr(0xFF & key)} is pressed, Quitting...")
            #    break
        #except Exception as e:
        #    logging.error(f"[Video Stream Monitor Thread] Exception: {e}")
        #    break

    # Cleanup
    logging.info("[Video Stream Monitor Thread] Stopping video stream monitor.")
    if out is not None:
        out.release()
        if current_recording_file:
            logging.info(f"[OpenCV Thread] Adding to queue: {current_recording_file}")
            # Use call_soon_threadsafe because we are in a different thread
            loop.call_soon_threadsafe(queue.put_nowait, current_recording_file)
    
    if cap.isOpened():
        cap.release()
        
    #cv2.destroyAllWindows()
    
    for _ in range(5):
        cv2.waitKey(1)

    # Signal the queue consumer that no more items will be added
    logging.info("[OpenCV Thread] Signaling queue consumer to stop.")
    loop.call_soon_threadsafe(queue.put_nowait, None) # Send sentinel
    logging.info("[OpenCV Thread] Finished.")


# ---------- Main Function ----------    
async def main():
    loop = asyncio.get_event_loop()
    video_queue = asyncio.Queue()
    
    archive_dir = os.getenv("ARCHIVE_DIR")
    os.makedirs(archive_dir, exist_ok=True)

    recording_dir = os.getenv("RECORDING_DIR")
    os.makedirs(recording_dir, exist_ok=True)
    
    logging.info("[Main Async] Staring Video Consumer")
    consumer_task = loop.create_task(consumer(video_queue, loop))
    
    
    rtsp_urls = os.getenv("RTSP_URLS")
    rtsp_urls_obj = eval(rtsp_urls)
    #currently oonly one url is supported
    rtsp_url = rtsp_urls_obj[0]
    logging.info(f"[Main Async] Starting Video Producer for URL: {rtsp_url}")
    producer_future = loop.run_in_executor(
        None, #use default ThreadPoolExecutor
        video_stream_monitor, 
        rtsp_url, 
        recording_dir,
        video_queue, 
        loop)
    
    #try:
    await producer_future 
    logging.info("[Main Async] Video Producer finished.")
    #except Exception as e:
    #    logging.error(f"[Main Async] Error in Video Producer: {e}")
    
    logging.info("[Main Async] Waiting for consumer to finish.")
    await video_queue.join() # Wait for all items in the queue to be processed
    logging.info("[Main Async] Consumer finished processing all items.")
    
    # Cancel the consumer task (it should exit gracefully after receiving None)
    # Although it exits on None, explicit cancellation is good practice
    if not consumer_task.done():
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            logging.error("[Main Async] Queue consumer task cancelled.")

    logging.info("[Main Async] All tasks completed.")
    

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format='%(filename)s:%(lineno)d -%(thread)d - %(asctime)s - %(levelname)s - %(message)s')
    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(__file__),  '.env')
    load_dotenv(env_path, interpolate=True, override=True, verbose=True)
    
    """
    try:
        logging.info("Starting motion detection.")
        asyncio.run(main())
        logging.info("Motion detection finished gracefully.")
    except KeyboardInterrupt:
        logging.info("Program interrupted by user.")
    except Exception as e:
        logging.error(f"An error occurred: {e}")
    finally:
        logging.info("[Main] Cleanup complete.")
        # Ensure OpenCV windows are closed if something went wrong
        cv2.destroyAllWindows()
        for _ in range(5): 
            cv2.waitKey(10)    
    """        
    
    logging.info("Starting motion detection.")
    asyncio.run(main())

    # Ensure OpenCV windows are closed if something went wrong
    #cv2.destroyAllWindows()
    for _ in range(5): 
        cv2.waitKey(10)    
