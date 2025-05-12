import logging
import subprocess

import os
import time

import asyncio

def stream_segmenter(rtsp_url: str, output_dir: str, segment_duration: int, 
    queue: asyncio.Queue, 
    loop: asyncio.AbstractEventLoop,
    shutdown_event: asyncio.Event = None
    ):
    """
    Runs FFmpeg as a subprocess to segment the RTSP stream into files.
    Monitors the output directory and puts finished segment paths onto the queue.
    This function runs in a separate thread.
    """
    logging.info(f"[Segmenter Thread] Starting stream segmenter for URL: {rtsp_url}")
    processed_segments = set()
    segment_filename_pattern = "segment_%Y%m%d_%H%M%S.mp4"
    output_pattern = os.path.join(output_dir, segment_filename_pattern)

    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    ffmpeg_cmd = [
        "ffmpeg", #command to run
        '-loglevel', 'error', # Reduce console spam, increase on debug
        '-rtsp_transport', 'tcp', # Often more reliable
        '-i', rtsp_url,
        '-c:v', 'copy',       # Try to copy video stream without re-encoding (low CPU)
        '-an',                # No audio
        '-f', 'segment',
        '-segment_time', str(segment_duration),
        '-segment_format', 'mp4',
        '-strftime', '1',     # Enable timestamp formatting in filename
        '-reset_timestamps', '1', # Start timestamps from 0 for each segment
        output_pattern
    ]
    
    poll_interval = 1

    logging.info(f"[Segmenter Thread] Running FFmpeg command: {' '.join(ffmpeg_cmd)}")
    process = None
    try:
        process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Monitor the output directory for new segment files
        # as the command runs, it will create lots of files for each segment util it stops
        while process.poll() is None and not shutdown_event.is_set(): # While ffmpeg is running
            try:
                
                for filename in os.listdir(output_dir):
                    if filename.startswith("segment_") and filename.endswith(".mp4"):
                        full_path = os.path.join(output_dir, filename)
                        if full_path not in processed_segments:
                             # Basic check: ensure file size is > 0 and mod time is slightly old
                             try:
                                 stat_info = os.stat(full_path)
                                 if stat_info.st_size > 0 and (time.time() - stat_info.st_mtime) > segment_duration: # Wait 2s after last write
                                     logging.info(f"[Segmenter Thread] Found new segment: {full_path}")
                                     loop.call_soon_threadsafe(queue.put_nowait, full_path)
                                     processed_segments.add(full_path)
                             except FileNotFoundError:
                                 continue # File might have been deleted by detector quickly
                             except Exception as e:
                                 logging.error(f"[Segmenter Thread] Error stating file {full_path}: {e}")

                # Sleep only if no new files were found in this pass
                time.sleep(poll_interval)
            except Exception as e:
                logging.error(f"[Segmenter Thread] Error scanning directory {output_dir}: {e}")
                time.sleep(poll_interval) # Avoid busy-loop on error

        logging.info(f"[Segmenter Thread] FFmpeg process exited with code: {process.returncode}")
        stderr_output = process.stderr.read().decode(errors='ignore')
        if process.returncode != 0:
             logging.error(f"[Segmenter Thread] FFmpeg Error Output:\n{stderr_output}")
        else:
             logging.info(f"[Segmenter Thread] FFmpeg stderr (might contain warnings):\n{stderr_output}")


    except FileNotFoundError:
        logging.error(f"[Segmenter Thread] Error: 'ffmpeg command not found. Please ensure FFmpeg is installed and in PATH.")
    except Exception as e:
        logging.error(f"[Segmenter Thread] An unexpected error occurred: {e}", exc_info=True)
    finally:
        if process and process.poll() is None:
            logging.warning("[Segmenter Thread] Terminating FFmpeg process...")
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logging.error("[Segmenter Thread] FFmpeg did not terminate gracefully, killing.")
                process.kill()
        logging.info("[Segmenter Thread] Performing final segment scan...")
        # Final scan after FFmpeg exits
        try:
            for filename in os.listdir(output_dir):
                 if filename.startswith("segment_") and filename.endswith(".mp4"):
                    full_path = os.path.join(output_dir, filename)
                    if full_path not in processed_segments:
                        logging.info(f"[Segmenter Thread] Found leftover segment: {full_path}")
                        loop.call_soon_threadsafe(queue.put_nowait, full_path)
                        processed_segments.add(full_path)
        except Exception as e:
            logging.error(f"[Segmenter Thread] Error during final scan: {e}")

        # Signal the detector that no more segments will be produced
        logging.info("[Segmenter Thread] Signaling detector to stop.")
        loop.call_soon_threadsafe(queue.put_nowait, None)
        logging.info("[Segmenter Thread] Stream segmenter finished.")
        
async def consumer(queue):
    while True:
        segment_file = await queue.get()
        if segment_file is None:
            logging.info("[Main Async] No more segments to process, consumer exiting.")
            queue.task_done()
            break
        logging.info(f"[Main Async] Consumed segment file: {segment_file}")
        # Process the segment file here
        # For example, you can pass it to the detector for further processing
        # detector.process_segment(segment_file)
        queue.task_done()        

async def main():
    recording_dir = os.getenv("RECORDING_DIR")
    if not recording_dir:
        logging.error("RECORDING_DIR environment variable is not set.")
        raise ValueError("RECORDING_DIR is not set.")
    
    rtsp_urls = os.getenv("RTSP_URLS")
    rtsp_urls_obj = eval(rtsp_urls)
    #currently oonly one url is supported
    rtsp_url = rtsp_urls_obj[0]
    logging.info(f"[Main Async] Starting Video Producer for URL: {rtsp_url}")
    
    loop = asyncio.get_event_loop()
    segment_file_queue = asyncio.Queue()
    shutdown_event = asyncio.Event()
    
    # Start the stream segmenter in a separate thread
    duration_in_min = 1
    segmenter_task = loop.run_in_executor(
        None, stream_segmenter, rtsp_url, recording_dir, duration_in_min * 60, segment_file_queue, loop, shutdown_event)
    # Wait for the segmenter to finish
    # create a simple consumer to read from the queue
    
    consumer_task = loop.create_task(consumer(segment_file_queue))
    # Run the consumer and segmenter tasks concurrently
    try:
        await asyncio.gather(consumer_task, segmenter_task )
    except KeyboardInterrupt:
        logging.info("[Main Async] Keyboard interrupt received, stopping...")
        shutdown_event.set()
    except Exception as e:
        logging.error(f"[Main Async] Error in main loop: {e}")
    finally:
        logging.info("[Main Async] Cleaning up...")
        if not segmenter_task.done():
            segmenter_task.cancel()
        if not consumer_task.done():
            consumer_task.cancel()
       
        
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format='%(filename)s:%(lineno)d -%(thread)d - %(asctime)s - %(levelname)s - %(message)s')
    env_path = os.path.join(os.path.dirname(__file__),  '..', '.env')
    if not os.path.exists(env_path):
        logging.warning(f"Environment file {env_path} not found")
        raise FileNotFoundError(f"Environment file {env_path} not found")
    
    from dotenv import load_dotenv
    load_dotenv(env_path)
    
    # Check if the required environment variables are set
    asyncio.run(main())