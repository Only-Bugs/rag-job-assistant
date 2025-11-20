"""Profile service handling default + user overrides."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

from rag.config.settings import RAG_DIR
from rag.utils.helpers import ensure_dir

PROFILE_STORE_PATH = RAG_DIR / "profile_settings.json"

DEFAULT_PROFILE: Dict[str, Any] = {
    "name": "Prabhakar Reddy Shashank",
    "title": "Full-Stack Developer | Cloud Engineer | Applied AI Engineer",
    "location": "Melbourne, Australia",
    "target_role": "Full-Stack / Cloud Engineer with Applied AI",
    "domain_focus": "Cloud, Backend, Applied ML Systems",
    "persona_tone": "Technical, concise, outcome-oriented",
    "role_keywords": [
        "Full-Stack Development",
        "Cloud Engineering",
        "Serverless",
        "Applied Machine Learning",
        "LLM Applications",
        "Backend Engineering",
        "Distributed Systems",
    ],
    "email": "shashank.dev.au@gmail.com",
    "phone": "+61 XXX XXX XXX",
    "links": [
        "https://github.com/only-bugs",
        "https://www.linkedin.com/in/prabhakar-reddy-shashank",
    ],
    "skills": [
        "JavaScript",
        "TypeScript",
        "Python",
        "Java",
        "React",
        "React Native (Expo)",
        "Node.js",
        "Express.js",
        "FastAPI",
        "AWS Lambda",
        "API Gateway",
        "Aurora Serverless",
        "S3",
        "Cognito",
        "CloudWatch",
        "Docker",
        "CI/CD",
        "ECS Fargate",
        "Terraform",
        "Applied Machine Learning",
        "TensorFlow Lite",
        "YOLO",
        "Audio/Image/Video Inference",
        "RAG Systems",
        "Vector Databases",
        "System Design",
        "Architecture",
        "Problem Solving",
        "Cross-cultural Collaboration",
        "Teamwork",
        "Communication",
    ],
    "achievements": [
        "Led engineering for sustainability-focused applications including Verde and NutriBuddy.",
        "Designed and deployed production-grade AWS serverless architectures (Lambda, Aurora, API Gateway, Secrets Manager).",
        "Built multimodal inference systems (audio, image, video) using Docker, TFLite, YOLO, and AWS Fargate.",
        "Won Monash Postgraduate Industry Experience Expo for high-impact engineering and real-world application.",
        "Created a Job Application RAG Assistant capable of parsing job descriptions and generating tailored applications.",
        "Developed multiple full-stack apps and cloud systems used in real-world demos and industry showcases.",
    ],
    "pitch": (
        "I build practical, production-ready software across full-stack, cloud, and applied AI. "
        "My work focuses on turning ideas into reliable systems — from React Native apps and backend services "
        "to serverless architectures and multimodal ML inference pipelines. I enjoy solving real problems and "
        "engineering systems that are simple, scalable, and genuinely useful."
    ),
    "role_preferences": {
        "industry": "Cloud + Applied AI",
        "role_description": "Full-stack, backend, and cloud engineering with production ML experience",
        "default_prompt_role": "Full-stack and cloud engineering job application assistant",
    },
}


def _ensure_profile_file() -> None:
    if PROFILE_STORE_PATH.exists():
        return
    ensure_dir(PROFILE_STORE_PATH.parent)
    with PROFILE_STORE_PATH.open("w", encoding="utf-8") as fh:
        json.dump(DEFAULT_PROFILE, fh, indent=2)


def load_profile() -> Dict[str, Any]:
    _ensure_profile_file()
    try:
        with PROFILE_STORE_PATH.open("r", encoding="utf-8") as fh:
            profile = json.load(fh)
    except json.JSONDecodeError:
        profile = deepcopy(DEFAULT_PROFILE)
        save_profile(profile)
    return profile


def save_profile(profile: Dict[str, Any]) -> None:
    ensure_dir(PROFILE_STORE_PATH.parent)
    with PROFILE_STORE_PATH.open("w", encoding="utf-8") as fh:
        json.dump(profile, fh, indent=2)


def reset_profile() -> Dict[str, Any]:
    ensure_dir(PROFILE_STORE_PATH.parent)
    with PROFILE_STORE_PATH.open("w", encoding="utf-8") as fh:
        json.dump(DEFAULT_PROFILE, fh, indent=2)
    return deepcopy(DEFAULT_PROFILE)


__all__ = [
    "DEFAULT_PROFILE",
    "PROFILE_STORE_PATH",
    "load_profile",
    "save_profile",
    "reset_profile",
]
