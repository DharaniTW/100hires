import requests
import os

API_KEY = os.environ.get("SUPADATA_API_KEY")

os.makedirs("youtube-transcripts", exist_ok=True)

videos = [
     ("dmb3dMZpa2A", "aleyda-solis"),
    ("2nJkT8zOzcM", "lily-ray"),
    ("eWEx2lA6QOM", "kyle-roof"),
    ("uH12O-6jx0U", "cyrus-shepard"),
    ("-fK3OaJ9Mjk", "matt-diggity"),
    ("39o0uYPo4jU", "neil-patel"),
    ("jQXvbeYF5go", "kevin-indig"),
    ("6ACNF0Dsqac", "brendan-hufford"),
    ("EFEvL1JnTTg", "nick-zviadadze"),
    ("tXQnRjgG-t8", "eli-schwartz"),
]

for video_id, author in videos:
    try:
        print(f"Fetching transcript for {author}...")

        response = requests.get(
            "https://api.supadata.ai/v1/youtube/transcript",
            headers={"x-api-key": API_KEY},
            params={
                "videoId": video_id,
                "text": "true",
            }
        )

        data = response.json()

        if response.status_code != 200:
            print(f"❌ Failed {author}: {data}")
            continue

        content = data.get("content", "")
        filename = f"youtube-transcripts/{author}.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(content)

        print(f"✅ Saved {author}")

    except Exception as e:
        print(f"❌ Error {author}: {e}")