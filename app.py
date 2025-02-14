import streamlit as st
import math
import re
from fpdf import FPDF
from googleapiclient.discovery import build
import firebase_admin
from firebase_admin import credentials, auth, firestore
from datetime import datetime, timezone
import google.generativeai as genai  # For Gemini API
from youtube_transcript_api import YouTubeTranscriptApi  # For fetching transcripts
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptAvailable
import pytz
from datetime import datetime
import time
from tenacity import retry, stop_after_attempt, wait_exponential
from googletrans import Translator

# -------------------------------
# Firebase Initialization
# -------------------------------
if not firebase_admin._apps:
    cred = credentials.Certificate("firebase-credentials.json.json")  # Replace with your Firebase credentials file
    firebase_admin.initialize_app(cred)

# Initialize Firestore
db = firestore.client()

# -------------------------------
# API Keys
# -------------------------------
YOUTUBE_API_KEY = "AIzaSyBBbpxCpuwp7MJYcDmgMCkkO6j3yhtsG7U"  # Replace with your YouTube API key
GEMINI_API_KEY = "AIzaSyATDiUoEH3ckyy6fw-pRZD63P1e-dxGivI"  # Replace with your Gemini API key

# Initialize Gemini API
genai.configure(api_key=GEMINI_API_KEY)

# -------------------------------
# Helper Functions
# -------------------------------
def convert_utc_to_ist(utc_time):
    """
    Convert UTC time string to IST.
    """
    local_tz = pytz.timezone("Asia/Kolkata")
    local_time = utc_time.astimezone(local_tz)
    return local_time

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
def translate_text(text: str, src_lang: str, dest_lang: str = 'en') -> str:
    """
    Translate text from source language to destination language.
    """
    try:
        translator = Translator()
        translation = translator.translate(text, src=src_lang, dest=dest_lang)
        return translation.text
    except Exception as e:
        st.error(f"Error translating text: {e}")
        return text  # Return original text if translation fails

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

def fetch_transcript(video_id: str) -> str:
    """
    Fetch the transcript for a YouTube video using YouTubeTranscriptApi.
    """
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id,languages=['en'])
        return " ".join([entry['text'] for entry in transcript])
    except NoTranscriptAvailable:
        try:
            # Fallback to Telugu if English is not available
            transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['te'])
            telugu_transcript = " ".join([entry['text'] for entry in transcript])
        except NoTranscriptAvailable:    
            try:
                # Fallback to Hindi if Telugu is not available
                transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['hi'])
                return " ".join([entry['text'] for entry in transcript])
            except NoTranscriptAvailable:
                # Fallback to any available language (auto-generated)
                transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
                for transcript in transcript_list:
                    if transcript.is_generated:  # Check if it's auto-generated
                        transcript_fetched = transcript.fetch()
                        return " ".join([entry['text'] for entry in transcript_fetched])
            except Exception as e:
                st.error(f"No English, Telugu, or auto-generated transcript available for video {video_id}: {e}")
                return None
    except TranscriptsDisabled:
        st.error(f"Transcripts are disabled for video {video_id}.")
        return None
    except Exception as e:
        st.error(f"Error fetching transcript for video {video_id}: {e}")
        return None
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def generate_questions_and_summary(transcript: str) -> dict:
    """
    Generate a summary, questions, and answers using the Gemini API.
    """
    try:
        model = genai.GenerativeModel('gemini-pro')
        
        # Generate summary
        summary_prompt = f"Summarize the following transcript in 100 words:\n{transcript}"
        summary_response = model.generate_content(summary_prompt)
        summary = summary_response.text if summary_response else "Summary generation failed"
        
        # Generate questions and answers
        qa_prompt = f"Generate 3 questions and answers based on the following transcript:\n{transcript}"
        qa_response = model.generate_content(qa_prompt)
        qa = qa_response.text if qa_response else "Q&A generation failed"
        
        return {
            "summary": summary,
            "qa": qa
        }
    except Exception as e:
        st.error(f"Error generating questions and summary: {e}")
        raise # Return structured data even on failure

def create_pdf_for_day(day: int, videos: list, transcripts_data: list) -> str:
    """
    Generate a PDF file for the specified day containing the video details, transcripts, summaries, and Q&A.
    """
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # Set font for the entire document
    pdf.set_font("Arial", size=12)  # Corrected font setting
    
    # Title
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, f"Daily Study Material - Day {day}", ln=True, align="C")
    pdf.ln(10)
    
    # Videos section
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, "Videos for Today:", ln=True)
    pdf.set_font("Arial", size=12)  # Corrected font setting
    
    for idx, video in enumerate(videos, 1):
        duration_hours = round(video['length'] / 3600, 2)
        pdf.multi_cell(0, 10, f"{idx}. {video['title']} ({duration_hours} hours)")
        pdf.ln(2)
    
    # Add space between sections
    pdf.ln(10)
    
    # Transcripts, summaries, and Q&A
    for idx, data in enumerate(transcripts_data, 1):
        # Video header
        pdf.set_font("Arial", "B", 14)
        pdf.cell(0, 10, f"Video {idx}: {videos[idx-1]['title']}", ln=True)
        pdf.ln(5)
        
        # Full transcript (if available)
        if data.get('transcript'):
            pdf.set_font("Arial", "B", 12)
            pdf.cell(0, 10, "Transcript (Translated to English):", ln=True)
            pdf.set_font("Arial", size=10)
            pdf.multi_cell(0, 5, data['transcript'])
            pdf.ln(5)
        else:
            pdf.set_font("Arial", "I", 10)
            pdf.multi_cell(0, 5, "Transcript not available for this video.")
            pdf.ln(5)
        
        # Summary (if available)
        if data.get('summary'):
            pdf.set_font("Arial", "B", 12)
            pdf.cell(0, 10, "Summary:", ln=True)
            pdf.set_font("Arial", size=10)
            pdf.multi_cell(0, 5, data['summary'])
            pdf.ln(5)
        else:
            pdf.set_font("Arial", "I", 10)
            pdf.multi_cell(0, 5, "Summary not available for this video.")
            pdf.ln(5)
        
        # Q&A (if available)
        if data.get('qa'):
            pdf.set_font("Arial", "B", 12)
            pdf.cell(0, 10, "Questions & Answers:", ln=True)
            pdf.set_font("Arial", size=10)
            pdf.multi_cell(0, 5, data['qa'])
            pdf.ln(5)
        else:
            pdf.set_font("Arial", "I", 10)
            pdf.multi_cell(0, 5, "Q&A not available for this video.")
            pdf.ln(5)
        
        # Add page break if not last item
        if idx != len(transcripts_data):
            pdf.add_page()
    
    pdf_filename = f"daily_study_day_{day}.pdf"
    pdf.output(pdf_filename)
    return pdf_filename

# -------------------------------
# Firebase Authentication Functions
# -------------------------------

def register_user(email: str, password: str):
    """
    Register a new user with Firebase Authentication.
    """
    try:
        user = auth.create_user(email=email, password=password)
        current_utc_time = datetime.now(timezone.utc)
        current_ist_time = convert_utc_to_ist(current_utc_time)
        user_ref = db.collection('users').document(user.uid)
        user_ref.set({
            'registration_date': current_ist_time,
            'saved_schedule': {},
            'viewed_days': [],
            'watched_videos': {},
            'start_date': None
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
        load_user_data()
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
        update_data = {
            'saved_schedule': {str(k): v for k, v in st.session_state.saved_schedule.items()},
            'viewed_days': list(st.session_state.viewed_days),
            'watched_videos': st.session_state.watched_videos,
            'start_date': st.session_state.start_date
        }
        user_ref.set(update_data, merge=True)

def load_user_data():
    """
    Load user data (study plan and progress) from Firestore.
    """
    if st.session_state.user:
        user_ref = db.collection('users').document(st.session_state.user.uid)
        doc = user_ref.get()
        if doc.exists:
            data = doc.to_dict()
            st.session_state.saved_schedule = {int(k): v for k, v in data.get('saved_schedule', {}).items()}
            st.session_state.viewed_days = set(data.get('viewed_days', []))
            st.session_state.watched_videos = data.get('watched_videos', {})
            st.session_state.start_date = data.get('start_date')

# -------------------------------
# Progress Tracking Functions
# -------------------------------

def calculate_current_day():
    """
    Calculate the current day based on the study plan's start date.
    """
    if not st.session_state.start_date:
        return 1
    now = datetime.now(timezone.utc)
    start_date = st.session_state.start_date.replace(hour=0, minute=0, second=0, microsecond=0)  # Normalize start date to midnight
    delta =now - start_date
    current_day = delta.days + 1  # Add 1 to make day 1 the start date
    return current_day

def show_progress_sidebar():
    """
    Display a progress tracker in the sidebar.
    """
    if st.session_state.saved_schedule:
        with st.sidebar:
            st.subheader("Your Progress")
            total_days = len(st.session_state.saved_schedule)
            current_day = calculate_current_day()
            cols = st.columns(total_days)
            for day in range(1, total_days + 1):
                with cols[day - 1]:
                    if day > current_day:
                        st.markdown("⚫")  # Future day (locked)
                    elif day in st.session_state.viewed_days:
                        st.markdown("🟢")  # Completed day
                    else:
                        st.markdown("⚪")  # Current/Pending day
                    st.caption(f"Day {day}")
def generate_daily_schedule(videos, num_days):
    """
    Distributes videos across the given number of days.
    """
    if not videos or num_days <= 0:
        return {}

    schedule = {}
    videos_per_day = math.ceil(len(videos) / num_days)

    for i in range(num_days):
        start_idx = i * videos_per_day
        end_idx = start_idx + videos_per_day
        schedule[i + 1] = videos[start_idx:end_idx]  # Day starts from 1

    return schedule

# -------------------------------
# Streamlit App
# -------------------------------

# Initialize session state variables
if 'saved_schedule' not in st.session_state:
    st.session_state.saved_schedule = {}
if 'viewed_days' not in st.session_state:
    st.session_state.viewed_days = set()
if 'watched_videos' not in st.session_state:
    st.session_state.watched_videos = {}
if 'start_date' not in st.session_state:
    st.session_state.start_date = None
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
        st.session_state.clear()
        st.rerun()

# Main App Functionality
if st.session_state.user:
    # Add navigation radio
    app_section = st.radio(
        "Navigation",
        ["Study Plan", "Progress"],
        horizontal=True
    )
    
    if app_section == "Study Plan":
        st.title("YouTube Playlist Daily Study Planner")
        
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
                    st.write(f"Total estimated duration: {round(total_seconds / 3600, 2)} hours.")
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
                        st.write(f"Duration: {round(video['length'] / 3600, 2)} hours.")
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
            time_slot = st.selectbox("Select your preferred daily time slot:",options=["Morning", "Afternoon", "Evening", "Night"])
            if st.button("Save Study Plan"):
                st.session_state.saved_schedule = generate_daily_schedule(st.session_state.videos, days)
                st.session_state.start_date = datetime.now(timezone.utc)
                st.session_state.viewed_days = set()
                st.session_state.watched_videos = {}
                save_user_data()
                st.success("Study plan saved for your account!")

        # --- Step 3: Display Saved Daily Videos & Track Progress ---
        if st.session_state.saved_schedule:
            # Calculate current day
            current_day = calculate_current_day()
            show_progress_sidebar()

            
            day_videos = st.session_state.saved_schedule.get(current_day, [])
            
            if day_videos:
                st.header(f"Day {current_day} Videos")
                watched_videos = st.session_state.watched_videos.get(str(current_day), [])
                
                for idx, video in enumerate(day_videos):
                    if idx < len(watched_videos):
                        st.video(video['url'])
                        st.write(f"✅ Watched: {video['title']}")
                    elif idx == len(watched_videos):
                        st.video(video['url'])
                        st.write(video['title'])
                        if st.button(f"Mark Video {idx + 1} as Watched", key=f"watch_{current_day}_{idx}"):
                            st.session_state.watched_videos.setdefault(str(current_day), []).append(idx)
                            save_user_data()
                            st.rerun()
                        break
                    else:
                        break

                if len(watched_videos) == len(day_videos):
                    st.success("You've completed all videos for today!")

            else:
                st.info("No videos scheduled for today.")

    # Modify the "Progress" section in the Streamlit App
    elif app_section == "Progress":
        # --- New About Section ---
        st.header("👤 User Profile")
        
        # Basic user info
        st.subheader("Account Details")
        st.write(f"Email: {st.session_state.user.email}")
        
        # Add registration date (requires Firestore storage)
        try:
            user_ref = db.collection('users').document(st.session_state.user.uid)
            doc = user_ref.get()
            if doc.exists:
                user_data = doc.to_dict()
                registration_date_utc = user_data.get('registration_date', 'Not available')
                if registration_date_utc != 'Not available':
                # Convert Firestore timestamp to datetime if necessary
                    registration_date_utc = registration_date_utc.replace(tzinfo=timezone.utc)
                    # Convert UTC registration date to IST
                    registration_date_ist = convert_utc_to_ist(registration_date_utc)
                    registration_date_str = registration_date_ist.strftime("%Y-%m-%d %H:%M:%S %Z")
                else:
                    registration_date_str = registration_date_utc
                st.write(f"Registration Date: {registration_date_str}")
        except Exception as e:
            st.error(f"Error loading profile data: {e}")
        
        # Study statistics
        st.subheader("Study Statistics")
        if st.session_state.saved_schedule:
            total_days = len(st.session_state.saved_schedule)
            completed_days = len(st.session_state.viewed_days)
            st.write(f"Total Study Days: {total_days}")
            st.write(f"Completed Days: {completed_days}")
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
                st.session_state.saved_schedule = {}

                st.session_state.viewed_days = set()
                save_user_data()  # Save changes to Firestore
                st.success("Study plan deleted successfully!")
                st.rerun()  # Refresh the page
            elif action == "Reset Progress":
                st.session_state.viewed_days = set()
                save_user_data()  # Save changes to Firestore
                st.success("Study plan progress reset successfully!")
                st.rerun()  # Refresh the page
        show_progress_sidebar()
        st.header("Daily PDF Generation")
        if st.session_state.saved_schedule:
            current_day = calculate_current_day()
            if st.button("Generate Today's PDF"):
                day_videos = st.session_state.saved_schedule.get(current_day, [])
                if day_videos:
                    # Fetch transcripts and generate summaries/Q&A
                    transcripts_data = []
                    for video in day_videos:
                        # Extract video ID from URL
                        video_id = extract_video_id(video['url'])
                        transcript = fetch_transcript(video_id) or "Transcript not available"
                        
                        if transcript:
                            # Generate summary and Q&A
                            generated_data = generate_questions_and_summary(transcript)
                            transcripts_data.append({
                                "transcript": transcript,
                                "summary": generated_data["summary"],
                                "qa": generated_data["qa"]
                            })
                        else:
                            transcripts_data.append({
                                "transcript": "Transcript not available",
                                "summary": "Summary not available",
                                "qa": "Q&A not available"
                            })
                    
                    # Generate PDF with all data
                    pdf_filename = create_pdf_for_day(current_day, day_videos, transcripts_data)
                    with open(pdf_filename, "rb") as pdf_file:
                        st.download_button(
                            label="Download Today's PDF",
                            data=pdf_file,
                            file_name=pdf_filename,
                            mime="application/pdf"
                        )
                else:
                    st.error("No videos scheduled for today.")
else:
    st.warning("Please log in or register to use the app.Check < for Authentication")
