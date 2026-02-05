"""
LLM Prompts for Property Analysis.
Contains only the image regeneration prompt.
"""

image_regeneration_prompt = """You are an expert interior designer and renovation consultant.
Analyze these property images and regenerate them based on the user's feedback.

User Feedback: {user_feedback}

Instructions:
Analyze the provided images
Apply the user's renovation feedback to transform the space

Focus on:
- Applying the requested style changes
- Maintaining realistic proportions and lighting
- Keeping the core room structure while updating finishes, colors, and fixtures

Generate the renovated version of each image based on the user's requirements.
"""
