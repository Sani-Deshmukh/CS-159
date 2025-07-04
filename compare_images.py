from PIL import Image
from engine.utils import ProgramInterpreter
import base64
import requests
import json
import os
from config import OPENAI_API_KEY


GPT_TASK_PROMPT = (
    "You are given two images of the same scene and a difference heatmap. "
    "The difference heatmap is a binary image where the difference between the two images is highlighted in white. "
    "Generate AS MANY *specific and visually testable* questions that help identify differences between them as you can. "
    "Use the difference heatmap to generate questions that focus on the differences between the two images. "
    "Cover the following categories:\n"
    "- Presence or absence of objects (e.g. 'Is there a boat?')\n"
    "- Quantity (e.g. 'How many cars are there?')\n"
    "- Color (e.g. 'What is the color of the shirt?')\n"
    # "- Size (e.g. 'How large is the tree?')\n"
    # "- Spatial location (e.g. 'Where is the umbrella positioned?')\n"
    "- Shape or orientation (e.g. 'What shape is the object? Is it upright or tilted?')\n"
    "- Action or behavior (e.g. 'Is anyone walking? Is the dog sitting?')\n\n"
    "Write each question so it can be answered **independently** for each image — do not compare directly (e.g. not 'Which image has more trees?').\n\n"
    "Do not combine questions. Do not repeat the same wording.\n\n"

    "Each question should focus on a specific object, color, action, or spatial detail. "
    "Questions should have one word answers."
    # "Make sure each object is mentioned in at least one question."
    "Respond only with a JSON array of strings (no explanation, no Markdown)."
)

def encode_image_to_base64(image_path):
    with open(image_path, 'rb') as f:
        return base64.b64encode(f.read()).decode('utf-8')

#  Get comparison questions from GPT-4o Vision
def get_comparison_questions(img1_path, img2_path, diff_path):
    img1_b64 = encode_image_to_base64(img1_path)
    img2_b64 = encode_image_to_base64(img2_path)
    diff_b64 = encode_image_to_base64(diff_path)

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "gpt-4o",
        "max_tokens": 1000,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": GPT_TASK_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img1_b64}"}},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img2_b64}"}},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{diff_b64}"}}
                ]
            }
        ]
    }

    res = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
    if res.status_code != 200:
        raise RuntimeError(f"OpenAI API error: {res.status_code} - {res.text}")

    content = res.json()['choices'][0]['message']['content']
    print("\n🧾 Raw GPT Response:")
    print(content)

    try:
        if content.strip().startswith("```json"):
            stripped = content.strip().strip("```json").strip("```").strip()
            questions = json.loads(stripped)
            if isinstance(questions, list):
                return questions
    except Exception as e:
        print(f" Markdown-stripped JSON parse failed: {e}")

    try:
        # Try raw JSON or markdown-wrapped JSON
        stripped = content.strip()
        if stripped.startswith("```json"):
            stripped = stripped.strip("```json").strip("```").strip()
        elif stripped.startswith("```"):
            stripped = stripped.strip("```").strip()

        questions = json.loads(stripped)
        if isinstance(questions, list):
            return questions
    except Exception as e:
        print(f"JSON parse failed: {e}")

    try:
        # Try parsing from a numbered list (e.g. "1. What is...")
        lines = content.strip().splitlines()
        questions = [
            line.split('.', 1)[1].strip()
            for line in lines if '.' in line and len(line.split('.', 1)[1].strip()) > 0
        ]
        if len(questions) >= 3:
            return questions
    except Exception as e:
        print(f"Loose list parse failed: {e}")


    print("Failed to parse GPT response. Using fallback questions.")
    return [
        "What objects are visible in the image?",
        "What are the main colors present?",
        "What actions or activities are occurring?",
        "Describe the setting or background."
    ]


def execute_visprog_comparison(img1_path, img2_path, questions):
    difference_counter = 0
    img_left = Image.open(img1_path).convert("RGB")
    img_right = Image.open(img2_path).convert("RGB")
    img_left.thumbnail((640, 640), Image.Resampling.LANCZOS)
    img_right.thumbnail((640, 640), Image.Resampling.LANCZOS)

    state = {"LEFT": img_left, "RIGHT": img_right}
    interpreter = ProgramInterpreter(dataset='nlvr')

    print("\n GPT-Generated Questions & VisProg Results\n" + "=" * 60)
    for i, question in enumerate(questions, 1):
        print(f"\n ->> Question {i}: {question}")

        prog_L = f"ANSWER=VQA(image=LEFT,question='{question}')\nFINAL_ANSWER=RESULT(var=ANSWER)"
        prog_R = f"ANSWER=VQA(image=RIGHT,question='{question}')\nFINAL_ANSWER=RESULT(var=ANSWER)"

        try:
            left_ans, _, _ = interpreter.execute(prog_L, state, inspect=True)
            right_ans, _, _ = interpreter.execute(prog_R, state, inspect=True)

            print(f"  LEFT : {left_ans}")
            print(f"  RIGHT: {right_ans}")

            norm = lambda s: str(s).strip().lower()
            if norm(left_ans) != norm(right_ans):
                difference_counter += 1
            print(f"  ➤ Different? → {'Yes' if norm(left_ans) != norm(right_ans) else 'No'}")
        except Exception as e:
            print(f"  Error during VisProg execution: {e}")
        print("TOTAL DIFFERENCES FOUND:", difference_counter)


def compare_images(img1_path, img2_path, diff_path):
    if not (os.path.exists(img1_path) and os.path.exists(img2_path)):
        raise FileNotFoundError(" One or both image paths do not exist.")

    print("📡 Getting questions from GPT-4o Vision...")
    questions = get_comparison_questions(img1_path, img2_path, diff_path)

    print("\n Questions to test:")
    for i, q in enumerate(questions, 1):
        print(f"  {i}. {q}")

    execute_visprog_comparison(img1_path, img2_path, questions)


if __name__ == "__main__":
    img1_path = "assets/hard1.png"
    img2_path = "assets/hard2.png"
    diff_path = "assets/difference_heatmap.png"
    try:
        compare_images(img1_path, img2_path, diff_path)
    except Exception as e:
        print(f"\n Error: {e}")
        print("Make sure:")
        print("1. Your OpenAI API key is valid in config.py")
        print("2. The two image files exist")
        print("3. You are connected to the internet")
