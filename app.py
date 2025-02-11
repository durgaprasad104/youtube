import streamlit as st
import math
import re
from fpdf import FPDF
from googleapiclient.discovery import build
import firebase_admin
from firebase_admin import credentials, auth, firestore
from google.cloud.firestore_v1 import DELETE_FIELD

# -------------------------------
# Firebase Initialization
# -------------------------------
if not firebase_admin._apps:
    cred = credentials.Certificate("firebase-credentials.json.json")  # Replace with your Firebase service account key path
    firebase_admin.initialize_app(cred)

# Initialize Firestore
db = firestore.client()

# -------------------------------
# Hardcoded API Keys (for testing only)
# -------------------------------
YOUTUBE_API_KEY = "AIzaSyBBbpxCpuwp7MJYcDmgMCkkO6j3yhtsG7U"
GEMINI_API_KEY = "AIzaSyBDkfFS2B_usA3ie2aUGLIxyu-OoKbnyYk"

# -------------------------------
# Helper Functions
# -------------------------------

def extract_video_id(url: str) -> str:
    """
    Extract the video ID from a standard YouTube URL.
    """
    patterns = [
        r"v=([^&]+)",          # standard URL pattern
        r"youtu\.be/([^?&]+)"   # shortened URL pattern
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def extract_playlist_id(url: str) -> str:
    """
    Extract the playlist ID from a YouTube playlist URL.
    """
    match = re.search(r"list=([^&]+)", url)
    if match:
        return match.group(1)
    return None

def iso8601_duration_to_seconds(duration: str) -> int:
    """
    Convert an ISO 8601 duration string (e.g., PT1H2M3S) to total seconds.
    """
    regex = re.compile(
        r'P'                           # period designator
        r'(?:(?P<days>\d+)D)?'         # days
        r'(?:T'                        # time part begins with T
        r'(?:(?P<hours>\d+)H)?'        # hours
        r'(?:(?P<minutes>\d+)M)?'      # minutes
        r'(?:(?P<seconds>\d+)S)?'      # seconds
        r')?'
    )
    parts = regex.match(duration)
    if not parts:
        return 0
    parts = parts.groupdict()
    total = int(parts.get('days') or 0) * 86400 + \
            int(parts.get('hours') or 0) * 3600 + \
            int(parts.get('minutes') or 0) * 60 + \
            int(parts.get('seconds') or 0)
    return total

def fetch_video_details_youtube(video_id: str, youtube_api_key: str) -> dict:
    """
    Fetch details for a single YouTube video using YouTube Data API v3.
    Returns a dictionary with title, duration (in seconds), and video URL.
    """
    try:
        youtube = build('youtube', 'v3', developerKey=youtube_api_key)
        response = youtube.videos().list(
            part='snippet,contentDetails',
            id=video_id
        ).execute()
        items = response.get("items", [])
        if not items:
            st.error("No video details found. Check the video ID.")
            return None
        item = items[0]
        title = item["snippet"]["title"]
        duration_iso = item["contentDetails"]["duration"]
        seconds = iso8601_duration_to_seconds(duration_iso)
        return {
            "title": title,
            "length": seconds,
            "url": f"https://www.youtube.com/watch?v={video_id}"
        }
    except Exception as e:
        st.error(f"Error fetching video details: {e}")
        return None

def fetch_playlist_details_youtube(playlist_id: str, youtube_api_key: str) -> list:
    """
    Fetch details for all videos in a playlist using YouTube Data API v3.
    Returns a list of dictionaries with each video's title, duration (in seconds), and URL.
    """
    try:
        youtube = build('youtube', 'v3', developerKey=youtube_api_key)
        videos = []
        nextPageToken = None
        while True:
            response = youtube.playlistItems().list(
                part="snippet,contentDetails",
                playlistId=playlist_id,
                maxResults=50,
                pageToken=nextPageToken
            ).execute()
            items = response.get("items", [])
            video_ids = [item["contentDetails"]["videoId"] for item in items]
            video_response = youtube.videos().list(
                part="contentDetails,snippet",
                id=",".join(video_ids)
            ).execute()
            for vid_item in video_response.get("items", []):
                title = vid_item["snippet"]["title"]
                duration_iso = vid_item["contentDetails"]["duration"]
                seconds = iso8601_duration_to_seconds(duration_iso)
                video_url = f"https://www.youtube.com/watch?v={vid_item['id']}"
                videos.append({
                    "title": title,
                    "length": seconds,
                    "url": video_url
                })
            nextPageToken = response.get("nextPageToken")
            if not nextPageToken:
                break
        return videos
    except Exception as e:
        st.error(f"Error fetching playlist details: {e}")
        return None

def seconds_to_hours(seconds: int) -> float:
    """
    Convert seconds to hours (rounded to 2 decimals).
    """
    return round(seconds / 3600, 2)

def generate_daily_schedule(videos: list, total_days: int) -> dict:
    """
    Divide the list of videos evenly among the given number of days.
    Returns a dictionary mapping day number to the list of video details.
    """
    total_videos = len(videos)
    videos_per_day = math.ceil(total_videos / total_days)
    schedule = {}
    for day in range(1, total_days + 1):
        start_index = (day - 1) * videos_per_day
        schedule[day] = videos[start_index:start_index + videos_per_day]
    return schedule

def simulate_transcript(video: dict) -> str:
    """
    Simulate a transcript for the video. (Replace with a real transcript method as needed.)
    """
    return f"This is a simulated transcript for '{video['title']}'. It covers the main points and key details."

def generate_questions_for_video_gemini(video: dict, gemini_api_key: str) -> str:
    """
    Simulate generating quiz questions using the Gemini API.
    (Replace with an actual API call if available.)
    """
    transcript = simulate_transcript(video)
    simulated_questions = (
        f"1. What is the main topic of '{video['title']}'?\n"
        f"2. Name one key detail mentioned in the video.\n"
        f"3. How can you apply the content of '{video['title']}' in practice?"
    )
    return simulated_questions

def create_pdf_for_day(day: int, video_list: list, questions_dict: dict) -> str:
    """
    Generate a PDF file for the specified day containing the video details and quiz questions.
    Returns the filename of the generated PDF.
    """
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, f"Daily Study Material - Day {day}", ln=True, align="C")
    pdf.set_font("Arial", "", 12)
    pdf.ln(10)
    pdf.cell(0, 10, "Videos for Today:", ln=True)
    for idx, video in enumerate(video_list, start=1):
        duration_hours = seconds_to_hours(video['length'])
        pdf.cell(0, 10, f"{idx}. {video['title']} ({duration_hours} hours)", ln=True)
    pdf.ln(10)
    pdf.cell(0, 10, "Quiz Questions:", ln=True)
    for idx, video in enumerate(video_list, start=1):
        pdf.multi_cell(0, 10, f"Video {idx}: {video['title']}")
        pdf.multi_cell(0, 10, questions_dict.get(video['url'], "No questions generated."))
        pdf.ln(5)
    pdf_filename = f"daily_study_day_{day}.pdf"
    pdf.output(pdf_filename)
    return pdf_filename

# -------------------------------
# Progress Tracking Functions
# -------------------------------

def show_progress_sidebar():
    """Display a progress tracker in the sidebar."""
    if st.session_state.saved_schedule:
        with st.sidebar:
            st.subheader("Your Progress")
            days_total = len(st.session_state.saved_schedule)
            cols = st.columns(days_total)
            for day in range(1, days_total + 1):
                with cols[day - 1]:
                    if day in st.session_state.viewed_days:
                        st.markdown("🟢")  # Completed day
                    else:
                        st.markdown("⚪")  # Pending day
                    st.caption(f"Day {day}")

# -------------------------------
# Firebase Authentication Functions
# -------------------------------

def register_user(email: str, password: str):
    """
    Register a new user with Firebase Authentication.
    """
    try:
        user = auth.create_user(email=email, password=password)
        # Add registration date to Firestore
        user_ref = db.collection('users').document(user.uid)
        user_ref.set({
            'registration_date': firestore.SERVER_TIMESTAMP,
            'saved_schedule': {},
            'viewed_days': []
        })
        st.success("User registered successfully! Please log in.")
        return user
    except Exception as e:
        st.error(f"Error registering user: {e}")
        return None

def login_user(email: str, password: str):
    """
    Log in a user with Firebase Authentication.
    """
    try:
        user = auth.get_user_by_email(email)
        st.session_state.user = user
        load_user_data()  # Load saved data after login
        st.success("Logged in successfully!")
        return user
    except Exception as e:
        st.error(f"Error logging in: {e}")
        return None

def save_user_data():
    """
    Save user data (study plan and progress) to Firestore.
    """
    if st.session_state.user:
        user_ref = db.collection('users').document(st.session_state.user.uid)
        
        # Handle None case for saved_schedule
        saved_schedule_state = st.session_state.get('saved_schedule') or {}
        
        # Convert schedule keys to strings for Firestore compatibility
        saved_schedule = {
            str(day): videos 
            for day, videos in saved_schedule_state.items()
        }
        
        user_ref.set({
            'saved_schedule': saved_schedule,
            'viewed_days': list(st.session_state.get('viewed_days', set()))
        }, merge=True)

def load_user_data():
    """
    Load user data (study plan and progress) from Firestore.
    """
    if st.session_state.user:
        user_ref = db.collection('users').document(st.session_state.user.uid)
        doc = user_ref.get()
        if doc.exists:
            data = doc.to_dict()
            
            # Convert string keys back to integers
            loaded_schedule = data.get('saved_schedule', {})
            st.session_state.saved_schedule = {
                int(day): videos 
                for day, videos in loaded_schedule.items()
            }
            
            st.session_state.viewed_days = set(data.get('viewed_days', []))

# -------------------------------
# Streamlit App
# -------------------------------

# Initialize session state variables
if 'saved_schedule' not in st.session_state:
    st.session_state.saved_schedule = None
if 'viewed_days' not in st.session_state:
    st.session_state.viewed_days = set()
if 'user' not in st.session_state:
    st.session_state.user = None

# Authentication Section
st.sidebar.title("Authentication")
if not st.session_state.user:
    auth_option = st.sidebar.radio("Choose an option:", ["Login", "Register"])
    if auth_option == "Register":
        email = st.sidebar.text_input("Email")
        password = st.sidebar.text_input("Password", type="password")
        if st.sidebar.button("Register"):
            user = register_user(email, password)
    elif auth_option == "Login":
        email = st.sidebar.text_input("Email")
        password = st.sidebar.text_input("Password", type="password")
        if st.sidebar.button("Login"):
            user = login_user(email, password)
else:
    st.sidebar.success(f"Logged in as {st.session_state.user.email}")
    if st.sidebar.button("Logout"):
        st.session_state.user = None
        st.session_state.saved_schedule = None
        st.session_state.viewed_days = set()
        st.rerun()

# Main App Functionality
if st.session_state.user:
    # Add navigation radio
    app_section = st.radio(
        "Navigation",
        ["Study Plan", "About Me"],
        horizontal=True
    )
    
    if app_section == "Study Plan":
        st.title("YouTube Playlist Daily Study Planner")
        st.markdown("This app uses YouTube Data API v3 to fetch video details and simulates a Gemini API to generate quiz questions.")

        # --- Step 1: Input YouTube URL and Fetch Videos ---
        url = st.text_input("Paste your YouTube video or playlist URL here:")

        if url:
            playlist_id = extract_playlist_id(url)
            if playlist_id:
                st.info("Detected a playlist URL. Fetching playlist details...")
                videos = fetch_playlist_details_youtube(playlist_id, YOUTUBE_API_KEY)
                if videos:
                    st.success(f"Found {len(videos)} videos in this playlist.")
                    total_seconds = sum(video['length'] for video in videos)
                    st.write(f"Total estimated duration: {seconds_to_hours(total_seconds)} hours.")
                    st.write("First few videos:")
                    for video in videos[:5]:
                        st.write(f"- {video['title']}")
                    st.session_state.videos = videos
                else:
                    st.error("Could not fetch playlist details. Please check the URL and API key.")
            else:
                video_id = extract_video_id(url)
                if video_id:
                    st.info("Detected a single video URL. Fetching video details...")
                    video = fetch_video_details_youtube(video_id, YOUTUBE_API_KEY)
                    if video:
                        st.success(f"Video found: {video['title']}")
                        st.write(f"Duration: {seconds_to_hours(video['length'])} hours.")
                        st.session_state.videos = [video]
                    else:
                        st.error("Could not fetch video details. Please check the URL and API key.")
                else:
                    st.error("Could not parse the YouTube URL. Please ensure it is valid.")

        # --- Step 2: Set Up and Save Study Plan ---
        if "videos" in st.session_state:
            st.header("Set Up Your Study Plan")
            total_videos = len(st.session_state.videos)
            days = st.number_input("Enter the number of days to complete these videos:", 
                                   min_value=1, max_value=100, value=3, step=1)
            time_slot = st.selectbox("Select your preferred daily time slot:",
                                     options=["Morning", "Afternoon", "Evening", "Night"])
            videos_per_day = math.ceil(total_videos / days)
            st.write(f"Approximately {videos_per_day} videos per day will be scheduled.")
            schedule = generate_daily_schedule(st.session_state.videos, days)
            st.write("### Your Daily Schedule Preview:")
            for day_num in schedule:
                st.write(f"Day {day_num}:")
                for vid in schedule[day_num]:
                    st.write(f"- {vid['title']}")
            if st.button("Save Study Plan"):
                st.session_state.saved_schedule = schedule
                st.session_state.viewed_days = set()
                save_user_data()  # Save the study plan to Firestore
                st.success("Study plan saved for your account!")

        # --- Progress Tracker ---
        if st.session_state.saved_schedule:
            show_progress_sidebar()

            # --- Step 3: Display Saved Daily Videos & Track Progress ---
            st.header("Your Saved Daily Videos")
            view_day = st.number_input("Select a day to view today's videos:", 
                                       min_value=1, 
                                       max_value=len(st.session_state.saved_schedule), 
                                       value=1, 
                                       step=1)
            
            # Track viewed days
            if view_day not in st.session_state.viewed_days:
                st.session_state.viewed_days.add(view_day)
                save_user_data()  # Save progress to Firestore
            
            # Display videos for selected day
            day_videos = st.session_state.saved_schedule.get(view_day, [])
            if day_videos:
                st.subheader(f"Videos for Day {view_day}:")
                for video in day_videos:
                    st.markdown(f"### {video['title']}")
                    st.video(video["url"])
                    with st.expander("Show Transcript"):
                        transcript = simulate_transcript(video)
                        st.write(transcript)
            else:
                st.info("No videos scheduled for this day.")

            # --- Step 4: PDF Generation ---

            # --- Step 4: PDF Generation ---
            st.header("Daily PDF Generation")
            st.write("Select a day and click the button to generate a PDF with that day's study materials and quiz questions.")
            selected_day = st.number_input("Select day number:", 
                                        min_value=1, 
                                        max_value=len(st.session_state.saved_schedule), 
                                        value=1, 
                                        step=1)
            if st.button("Generate Daily PDF"):
                day_videos = st.session_state.saved_schedule.get(selected_day, [])
                if not day_videos:
                    st.error("No videos scheduled for the selected day.")
                else:
                    questions_dict = {}
                    with st.spinner("Generating quiz questions..."):
                        for video in day_videos:
                            questions = generate_questions_for_video_gemini(video, GEMINI_API_KEY)
                            questions_dict[video['url']] = questions
                    pdf_filename = create_pdf_for_day(selected_day, day_videos, questions_dict)
                    st.success(f"PDF generated: {pdf_filename}")
                    with open(pdf_filename, "rb") as pdf_file:
                        st.download_button(
                            label="Download Daily PDF",
                            data=pdf_file,
                            file_name=pdf_filename,
                            mime="application/pdf"
                        )
        
    elif app_section == "About Me":
        # --- New About Section ---
        st.header("👤 User Profile")
        
        # Basic user info
        st.subheader("Account Details")
        st.write(f"*Email:* {st.session_state.user.email}")
        
        # Add registration date (requires Firestore storage)
        try:
            user_ref = db.collection('users').document(st.session_state.user.uid)
            doc = user_ref.get()
            if doc.exists:
                user_data = doc.to_dict()
                st.write(f"*Registration Date:* {user_data.get('registration_date', 'Not available')}")
        except Exception as e:
            st.error(f"Error loading profile data: {e}")
        
        # Study statistics
        st.subheader("Study Statistics")
        if st.session_state.saved_schedule:
            total_days = len(st.session_state.saved_schedule)
            completed_days = len(st.session_state.viewed_days)
            st.write(f"*Total Study Days:* {total_days}")
            st.write(f"*Completed Days:* {completed_days}")
            st.progress(completed_days / total_days)
        else:
            st.info("No active study plan found")
        
        # Delete or Reset options
        st.subheader("Manage Study Plan")
        action = st.radio(
            "Choose an action:",
            ["Delete Study Plan", "Reset Progress"],
            horizontal=True
        )
        
        if st.button("Confirm Action"):
            if action == "Delete Study Plan":
                st.session_state.saved_schedule = None
                st.session_state.viewed_days = set()
                save_user_data()  # Save changes to Firestore
                st.success("Study plan deleted successfully!")
                st.rerun()  # Refresh the page
            elif action == "Reset Progress":
                st.session_state.viewed_days = set()
                save_user_data()  # Save changes to Firestore
                st.success("Study plan progress reset successfully!")
                st.rerun()  # Refresh the page
else:
            st.warning("Please log in or register to use the app, Check the Authentication left side")
