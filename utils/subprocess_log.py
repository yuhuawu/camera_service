import logging
import threading

def log_subprocess_output(pipe, log_level, log_name):
    #Reads lines from a subprocess pipe and logs them.
    try:
        for line in iter(pipe.readline, b''):
            log_message = line.decode(errors='ignore').strip()
            if log_message: # Avoid logging empty lines
                logging.log(log_level, f"[{log_name}] {log_message}")
    except Exception as e:
        logging.error(f"Error reading log pipe for {log_name}: {e}")
    finally:
        pipe.close()


def start_subprocess_log_threads(process, base_log_name="ffmpeg"):
    """
    Starts daemon threads to log the stdout and stderr of a subprocess.
    Returns the stdout and stderr thread objects.
    """
    if not process or process.stdout is None or process.stderr is None:
        logging.error(f"[{base_log_name}] Process or its pipes are not available for logging.")
        return None, None

    stderr_log_prefix = f"{base_log_name}-stderr"
    stderr_thread = threading.Thread(
        target=log_subprocess_output,
        args=(process.stderr, logging.ERROR, stderr_log_prefix), # ffmpeg typically logs to stderr
        daemon=True,
        name=f"{stderr_log_prefix}-thread"
    )
    stderr_thread.start()
    
    stdout_log_prefix = f"{base_log_name}-stdout"
    stdout_thread = threading.Thread(
        target=log_subprocess_output,
        args=(process.stdout, logging.DEBUG, stdout_log_prefix), # ffmpeg stdout is usually less verbose or for progress
        daemon=True,
        name=f"{stdout_log_prefix}-thread"
    )
    stdout_thread.start()
    
    logging.debug(f"[{base_log_name}] Started logging threads for PID {process.pid}")
    return stdout_thread, stderr_thread

def stop_subprocess_log_threads(stdout_thread, stderr_thread, timeout=5):
    """
    Waits for the subprocess logging threads to complete.
    The threads should stop automatically when the subprocess pipes are closed.
    """
    thread_name = threading.current_thread().name
    logging.debug(f"[{thread_name}] Attempting to join logging threads.")
    if stderr_thread and stderr_thread.is_alive():
        logging.debug(f"[{thread_name}] Joining stderr logging thread...")
        stderr_thread.join(timeout=timeout)
        if stderr_thread.is_alive():
            logging.warning(f"[{thread_name}] Stderr logging thread did not join in time.")
            
    if stdout_thread and stdout_thread.is_alive():
        logging.debug(f"[{thread_name}] Joining stdout logging thread...")
        stdout_thread.join(timeout=timeout)
        if stdout_thread.is_alive():
            logging.warning(f"[{thread_name}] Stdout logging thread did not join in time.")
    logging.debug(f"[{thread_name}] Finished joining logging threads.")
