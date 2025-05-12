"""
write a new version of the capture.py
simplify the code: only use ffmpeg to capture the live stream and output the segments
"""

import os
import subprocess
import time
from datetime import datetime, timedelta
import threading

SEGMENT_TIME = 1 * 60
RECONNECT_DELAY_SECONDS = 10

from utils.subprocess_log import start_subprocess_log_threads, stop_subprocess_log_threads


def recording_and_segment_func(stop_event, 
                               segment_duration,
                               output_dir,
                               live_stream_url):
    """
    Solely responsible for continuously recording the live stream to 1-hour MP4 segments
    using an ffmpeg subprocess.
    """
    threading_name = threading.current_thread().name
    logging.info(f"[{threading_name}] Started. Receive from: {live_stream_url} to: {output_dir}")
    
    recorder_process = None
    subprocess_stdout_log_thread = None
    subprocess_stderr_log_thread = None
        
    try:
        while not stop_event.is_set():
            # Construct filename with current timestamp to ensure unique start for each ffmpeg instance
            # This helps if ffmpeg crashes and needs to be restarted by the loop.
            # The segmenter will still create files aligned to clock time if possible.
            segment_filename_pattern = "segment_%Y%m%d_%H%M%S.mp4"
            output_pattern = os.path.join(output_dir, segment_filename_pattern)

            ffmpeg_record_cmd = [
                'ffmpeg',
                '-loglevel', 'info',
                '-rtsp_transport', 'tcp',
                '-i', live_stream_url,
                '-c:v', 'copy',
                '-c:a', 'copy', # Or 'aac' if copy causes issues and some audio transcoding is fine
                '-map', '0', # Map all streams from input
                '-f', 'segment',
                '-segment_time', str(segment_duration),
                '-segment_format', 'mp4',
                '-strftime', '1',
                '-fflags', '+genpts',
                output_pattern
            ]
            logging.info(f"[{threading_name}] Starting/Restarting continuous recording: {' '.join(ffmpeg_record_cmd)}")
            recorder_process = subprocess.Popen(ffmpeg_record_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            if subprocess_stdout_log_thread is None and subprocess_stderr_log_thread is None:
                # Start logging threads for the ffmpeg process
                subprocess_stdout_log_thread, subprocess_stderr_log_thread = start_subprocess_log_threads(recorder_process, base_log_name="ffmpeg_recorder")
            else:
                # If threads are already running, just log the restart
                raise Exception("Logging threads already running. This should not happen.")

            # Monitor the ffmpeg process and the stop event
            while not stop_event.is_set():
                if recorder_process.poll() is not None: # ffmpeg has exited
                    logging.info(f"[{threading_name}] ffmpeg recorder process {recorder_process.pid} exited with code {recorder_process.returncode}.")
                    stop_subprocess_log_threads(subprocess_stdout_log_thread, subprocess_stderr_log_thread)
                    subprocess_stdout_log_thread = None
                    subprocess_stderr_log_thread = None
                    recorder_process = None
                    break # Break inner loop to restart ffmpeg
                
                stop_event.wait(1) # Check every second for recording process status and stop event

            if stop_event.is_set():
                # If stop event is set, terminate ffmpeg if it's still running
                if recorder_process.poll() is None:
                    logging.info(f"[{threading.current_thread().name}] Stop signal received. Terminating continuous recorder...")
                    recorder_process.terminate()
                    try:
                        recorder_process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        logging.warning("[RecordingProcess] ffmpeg recorder did not terminate gracefully, killing.")
                        recorder_process.kill()
                stop_subprocess_log_threads(subprocess_stdout_log_thread, subprocess_stderr_log_thread)
                subprocess_stdout_log_thread, subprocess_stderr_log_thread = None, None    
                break # Break outer loop

            if not stop_event.is_set():
                logging.info(f"[RecordingProcess] ffmpeg process ended unexpectedly. Restarting in {RECONNECT_DELAY_SECONDS}s...")
                stop_event.wait(RECONNECT_DELAY_SECONDS)
    except Exception as e:
        logging.info(f"[{threading.current_thread().name}] Exception {e} received. Stopping...")
    finally:
        print(f"DEBUG: [{threading_name}] In finally block of recording_and_segment_func.")
        logging.info(f"[{threading.current_thread().name}] Entering finally block for cleanup.")
        if recorder_process and recorder_process.poll() is None:
            logging.info(f"[{threading.current_thread().name}] Terminating ffmpeg process.")
            recorder_process.terminate()
            try:
                recorder_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logging.warning(f"[{threading.current_thread().name}] ffmpeg did not terminate gracefully, killing.")
                recorder_process.kill()
            # Optionally read and log any final stderr here
            stop_subprocess_log_threads(subprocess_stdout_log_thread, subprocess_stderr_log_thread)
            subprocess_stdout_log_thread, subprocess_stderr_log_thread = None, None
        logging.info(f"[{threading_name}] Stopped.")
        print(f"DEBUG: [{threading_name}] In finally block of recording_and_segment_func. End of function.")
        
from dotenv import load_dotenv
def main():
    """
    Main function to test the recording_and_segment_process.
    """
    env_path = os.path.join(os.path.dirname(__file__),  '..', '.env')
    if not os.path.exists(env_path):
        logging.error(f"Environment file {env_path} not found. Please create it or check the path.")
        exit(1) # Exit if .env is critical
    
    load_dotenv(env_path)
    
    # set up environment variables
    recording_dir = os.getenv("RECORDING_DIR")
    if not recording_dir:
        logging.error("RECORDING_DIR environment variable is not set.")
        raise ValueError("RECORDING_DIR is not set.")
    
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

    logging.info(f"[Main Async] Starting Video Producer for URL: {rtsp_url}")
    
    stop_event = threading.Event()
    
    # Create a stop event for the recording process
    segment_duration = 1 * 60 #test 
    
    recording_thread = threading.Thread(
        target=recording_and_segment_func,
        args=(stop_event, segment_duration, recording_dir, rtsp_url),
        name="RecordingThread",              
    )
    
    #recording_thread.daemon = True # Daemonize thread
   
    recording_thread.start()
   
    try:
        while recording_thread.is_alive():
            recording_thread.join(timeout=1)
            logging.info(f"[Main] Recording thread is alive. PID: {recording_thread.ident}")
    except KeyboardInterrupt:
        logging.info("[Main] Receive KeyboardStopping recording process...")
    finally:
        logging.info("[Main] Sending stop signal to child processes...")
        if not stop_event.is_set():
            stop_event.set()

        logging.info("[Main] Waiting for Recording Process to join...")
        if recording_thread.is_alive():
            recording_thread.join()       
            if recording_thread.is_alive():
                logging.warning("[Main] Recording thread did not join in time. Forcing exit.")
        logging.info("System shut down complete.")

import logging    
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s - %(process)d - %(thread)d - %(filename)s:%(lineno)d - %(levelname)s - %(message)s')
    main()