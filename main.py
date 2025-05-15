import logging
import os
import time
import multiprocessing

from detector import motion_detection_process

from dotenv import load_dotenv

from notifier.qq_mail import send_html_mail


def main():
    env_file = os.path.join(os.path.dirname(__file__), ".env")
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
    base_frame_img_path = os.path.join(os.path.dirname(__file__), base_frame_img_name)
    if not os.path.exists(base_frame_img_path):
        raise ValueError(f"BASE_FRAME_IMG_PATH: {base_frame_img_path} does not exist.")

    snapshot_dirname = os.getenv("SNAPSHOT_DIR")
    if not snapshot_dirname:
        raise ValueError("SNAPSHOT_DIR is not set.")
    snapshot_dir_path = os.path.join(os.path.dirname(__file__), snapshot_dirname)
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
                    mail_tile = f"Motion detected from {motion_start_time} to {motion_end_time}"
                    directory = snapshot_dir_path
                    send_html_mail(title=mail_tile, directory=directory, image_name=snap_img_name)                        
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