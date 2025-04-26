import cv2

def capture_rtsp_stream(rtsp_url):
    # Open a connection to the RTSP stream
    cap = cv2.VideoCapture(rtsp_url)

    if not cap.isOpened():
        print("Error: Unable to open the RTSP stream.")
        return

    print("RTSP stream opened successfully. Press 'q' to quit.")

    while True:
        # Read frames from the stream
        ret, frame = cap.read()

        if not ret:
            print("Error: Unable to read frame from the RTSP stream.")
            break

        # Display the frame
        cv2.imshow('RTSP Stream', frame)

        # Exit if 'q' is pressed
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    # Release the video capture object and close OpenCV windows
    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    # Replace this with your RTSP URL
    rtsp_url = "rtsp://ha:159357Hkvs24@192.168.1.203:554/Streaming/Channels/101"
    capture_rtsp_stream(rtsp_url)