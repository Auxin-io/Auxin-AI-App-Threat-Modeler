import json
import requests
import time
import re
from anthropic import Anthropic
from mistralai import Mistral, UserMessage
from openai import OpenAI, AzureOpenAI
import streamlit as st

from google import genai as google_genai
from groq import Groq
from utils import process_groq_response, create_reasoning_system_prompt

def dread_json_to_markdown(dread_assessment):
    # Create a clean Markdown table with proper spacing
    markdown_output = "| Threat Type | Scenario | Damage Potential | Reproducibility | Exploitability | Affected Users | Discoverability | Risk Score |\n"
    markdown_output += "|------------|----------|------------------|-----------------|----------------|----------------|-----------------|------------|\n"
    
    try:
        # Access the list of threats under the "Risk Assessment" key
        threats = dread_assessment.get("Risk Assessment", [])
        
        # If there are no threats, add a message row
        if not threats:
            markdown_output += "| No threats found | Please generate a threat model first | - | - | - | - | - | - |\n"
            return markdown_output
            
        for threat in threats:
            # Check if threat is a dictionary
            if isinstance(threat, dict):
                # Get values with defaults
                threat_type = threat.get('Threat Type', 'N/A')
                scenario = threat.get('Scenario', 'N/A')
                damage_potential = threat.get('Damage Potential', 0)
                reproducibility = threat.get('Reproducibility', 0)
                exploitability = threat.get('Exploitability', 0)
                affected_users = threat.get('Affected Users', 0)
                discoverability = threat.get('Discoverability', 0)
                
                # Calculate the Risk Score
                risk_score = (damage_potential + reproducibility + exploitability + affected_users + discoverability)
                
                # Escape any pipe characters in text fields to prevent table formatting issues
                threat_type = str(threat_type).replace('|', '\\|')
                scenario = str(scenario).replace('|', '\\|')
                
                # Ensure scenario text doesn't break table formatting by limiting length and removing newlines
                if len(scenario) > 100:
                    scenario = scenario[:97] + "..."
                scenario = scenario.replace('\n', ' ').replace('\r', '')
                
                # Add the row to the table with proper formatting
                markdown_output += f"| {threat_type} | {scenario} | {damage_potential} | {reproducibility} | {exploitability} | {affected_users} | {discoverability} | {risk_score:.2f} |\n"
            else:
                # Skip non-dictionary entries and log a warning
                markdown_output += "| Invalid threat | Threat data is not in the correct format | - | - | - | - | - | - |\n"
    except Exception as e:
        # Add a note about the error and a placeholder row
        markdown_output += "| Error | An error occurred while processing the DREAD assessment | - | - | - | - | - | - |\n"
    
    # Add a blank line after the table for better rendering
    markdown_output += "\n"
    return markdown_output


# Function to create a prompt to generate mitigating controls
def create_dread_assessment_prompt(threats):
    prompt = f"""
Act as a cybersecurity expert with over 20 years of experience in threat modeling using STRIDE and DREAD methodologies.
Your task is to generate a DREAD-based risk assessment for the following identified threats:
{threats}

Please provide the response in JSON format with a top-level key "Risk Assessment" that includes a list of threat objects. Each object must have the following fields:

"Threat Type": A string representing the STRIDE threat category (e.g., "Spoofing").
"Scenario": A brief description of the threat scenario.
"Damage Potential": An integer between 1 and 3 (3 = high impact).
"Reproducibility": An integer between 1 and 3.
"Exploitability": An integer between 1 and 3.
"Affected Users": An integer between 1 and 3.
"Discoverability": An integer between 1 and 3.
"Risk Score": The sum of the five values above, ranging from 5 to 15.

"Risk Rating": A classification based on the score:
12–15 → "Major"
8–11 → "Moderate"
5–7 → "Minor"

Use the following severity scale for each DREAD category:
1 = Low
2 = Medium
3 = High
Ensure the JSON response is correctly formatted and does not contain any additional text. Here is an example of the expected JSON response format:
{{
  "Risk Assessment": [
    {{
      "Threat Type": "Spoofing",
      "Scenario": "An attacker could create a fake OAuth2 provider and trick users into logging in through it.",
      "Damage Potential": 3,
      "Reproducibility": 2,
      "Exploitability": 2,
      "Affected Users": 3,
      "Discoverability": 2
    }},
    {{
      "Threat Type": "Spoofing",
      "Scenario": "An attacker could intercept the OAuth2 token exchange process through a Man-in-the-Middle (MitM) attack.",
      "Damage Potential": 3,
      "Reproducibility": 2,
      "Exploitability": 2,
      "Affected Users": 3,
      "Discoverability": 2
    }}
  ]
}}
"""
    return prompt

def clean_json_response(response_text):
    import re
    # Remove markdown JSON code block if present
    json_pattern = r'```json\s*(.*?)\s*```'
    match = re.search(json_pattern, response_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # If no JSON code block, try to find content between any code blocks
    code_pattern = r'```\s*(.*?)\s*```'
    match = re.search(code_pattern, response_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # If no code blocks, return the original text
    return response_text.strip()

def get_dread_assessment(api_key, model_name, prompt):
    client = OpenAI(api_key=api_key)

    # For reasoning models (o1, o3, o3-mini, o4-mini), use a structured system prompt
    if model_name in ["o1", "o3", "o3-mini", "o4-mini"]:
        system_prompt = create_reasoning_system_prompt(
            task_description="Perform a DREAD risk assessment for the identified security threats.",
            approach_description="""1. For each threat in the provided threat model:
   - Analyze the threat type and scenario in detail
   - Evaluate Damage Potential (1-3):
     * Consider direct and indirect damage
     * Assess financial, reputational, and operational impact
   - Evaluate Reproducibility (1-3):
     * Assess how reliably the attack can be reproduced
     * Consider required conditions and resources
   - Evaluate Exploitability (1-3):
     * Analyze technical complexity
     * Consider required skills and tools
   - Evaluate Affected Users (1-3):
     * Determine scope of impact
     * Consider both direct and indirect users
   - Evaluate Discoverability (1-3):
     * Assess how easily the vulnerability can be found
     * Consider visibility and detection methods
2. Format output as JSON with 'Risk Assessment' array containing:
   - Threat Type
   - Scenario
   - Numerical scores (1-3) for each DREAD category"""
        )
    else:
        system_prompt = "You are a helpful assistant designed to output JSON."

    response = client.chat.completions.create(
        model=model_name,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
    )
    
    # Convert the JSON string in the 'content' field to a Python dictionary
    try:
        dread_assessment = json.loads(response.choices[0].message.content)
    except json.JSONDecodeError:
        # Handle error silently
        dread_assessment = {}
    
    return dread_assessment

def get_dread_assessment_azure(azure_api_endpoint, azure_api_key, azure_api_version, azure_deployment_name, prompt):
    client = AzureOpenAI(
        azure_endpoint = azure_api_endpoint,
        api_key = azure_api_key,
        api_version = azure_api_version,
    )

    response = client.chat.completions.create(
        model = azure_deployment_name,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "You are a helpful assistant designed to output JSON."},
            {"role": "user", "content": prompt}
        ]
    )

    # Convert the JSON string in the 'content' field to a Python dictionary
    try:
        dread_assessment = json.loads(response.choices[0].message.content)
    except json.JSONDecodeError:
        # Handle error silently
        dread_assessment = {}
    
    return dread_assessment

# Function to get DREAD risk assessment from the Google model's response.
def get_dread_assessment_google(google_api_key, google_model, prompt):
    """
    Generate a DREAD risk assessment using the Gemini API (Google AI) as per official documentation:
    https://ai.google.dev/gemini-api/docs/text-generation
    """
    client = google_genai.Client(api_key=google_api_key)
    system_instruction = (
        "You are a helpful assistant designed to output JSON. "
        "Only provide the DREAD risk assessment in JSON format with no additional text. "
        "Do not wrap the output in a code block."
    )

    is_gemini_2_5 = "gemini-2.5" in google_model.lower()

    try:
        from google.genai import types as google_types
        if is_gemini_2_5:
            config = google_types.GenerateContentConfig(
                system_instruction=system_instruction,
                thinking_config=google_types.ThinkingConfig(thinking_budget=1024)
            )
        else:
            config = google_types.GenerateContentConfig(
                system_instruction=system_instruction
            )
        response = client.models.generate_content(
            model=google_model,
            contents=[prompt],
            config=config
        )
        # Extract Gemini 2.5 'thinking' content if present
        thinking_content = []
        for candidate in getattr(response, 'candidates', []):
            content = getattr(candidate, 'content', None)
            if content and hasattr(content, 'parts'):
                for part in content.parts:
                    if hasattr(part, 'thought') and part.thought:
                        thinking_content.append(str(part.thought))
        if thinking_content:
            joined_thinking = "\n\n".join(thinking_content)
            st.session_state['last_thinking_content'] = joined_thinking
    except Exception as e:
        st.error(f"Error generating DREAD assessment with Google AI: {str(e)}")
        return {"Risk Assessment": []}

    cleaned = clean_json_response(response.text)

    try:
        dread_assessment = json.loads(cleaned)
        return dread_assessment
    except json.JSONDecodeError:
        return {}

# Function to get DREAD risk assessment from the Mistral model's response.
def get_dread_assessment_mistral(mistral_api_key, mistral_model, prompt):
    client = Mistral(api_key=mistral_api_key)

    response = client.chat.complete(
        model=mistral_model,
        response_format={"type": "json_object"},
        messages=[
            UserMessage(content=prompt)
        ]
    )

    try:
        # Convert the JSON string in the 'content' field to a Python dictionary
        dread_assessment = json.loads(response.choices[0].message.content)
    except json.JSONDecodeError:
        dread_assessment = {}

    return dread_assessment

# Function to get DREAD risk assessment from Ollama hosted LLM.
def get_dread_assessment_ollama(ollama_endpoint, ollama_model, prompt):
    """
    Get DREAD risk assessment from Ollama hosted LLM.
    
    Args:
        ollama_endpoint (str): The URL of the Ollama endpoint (e.g., 'http://localhost:11434')
        ollama_model (str): The name of the model to use
        prompt (str): The prompt to send to the model
        
    Returns:
        dict: The parsed JSON response containing the DREAD assessment
        
    Raises:
        requests.exceptions.RequestException: If there's an error communicating with the Ollama endpoint
        json.JSONDecodeError: If the response cannot be parsed as JSON
        KeyError: If the response doesn't contain the expected fields
    """
    if not ollama_endpoint.endswith('/'):
        ollama_endpoint = ollama_endpoint + '/'
    
    url = ollama_endpoint + "api/chat"

    max_retries = 3
    retry_delay = 2 # seconds

    data = {
        "model": ollama_model,
        "stream": False,
        "format": "json",
        "messages": [
            {
                "role": "system", 
                "content": """You are a cyber security expert with more than 20 years experience of using the DREAD risk assessment methodology to evaluate security threats. Your task is to analyze the provided application description and perform a DREAD assessment.

Please provide your response in JSON format with the following structure:
{
    "dread_assessment": [
        {
            "threat": "Description of the threat",
            "damage": "Score and explanation",
            "reproducibility": "Score and explanation",
            "exploitability": "Score and explanation",
            "affected_users": "Score and explanation",
            "discoverability": "Score and explanation",
            "risk_score": "Calculated total score"
        }
    ]
}"""
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
    }

    for attempt in range(max_retries):
        try:
            response = requests.post(url, json=data, timeout=60)  # Add timeout
            response.raise_for_status()  # Raise exception for bad status codes
            outer_json = response.json()
            
            try:
                # Access the 'content' attribute of the 'message' dictionary and parse as JSON
                dread_assessment = json.loads(outer_json["message"]["content"])
                return dread_assessment
                
            except (json.JSONDecodeError, KeyError):
                if attempt == max_retries - 1:  # Last attempt
                    raise
                time.sleep(retry_delay)
                continue
                
        except requests.exceptions.RequestException:
            if attempt == max_retries - 1:  # Last attempt
                raise
            time.sleep(retry_delay)
            continue

# Function to get DREAD risk assessment from the Anthropic model's response.
def get_dread_assessment_anthropic(anthropic_api_key, anthropic_model, prompt):
    client = Anthropic(api_key=anthropic_api_key)
    
    # Check if we're using extended thinking mode
    is_thinking_mode = "thinking" in anthropic_model.lower()
    
    # Check if we're using Claude 3.7
    is_claude_3_7 = "claude-3-7" in anthropic_model.lower()
    
    # If using thinking mode, use the actual model name without the "thinking" suffix
    actual_model = "claude-3-7-sonnet-latest" if is_thinking_mode else anthropic_model
    
    try:
        # Configure the request based on whether thinking mode is enabled
        if is_thinking_mode:
            response = client.messages.create(
                model=actual_model,
                max_tokens=24000,
                thinking={
                    "type": "enabled",
                    "budget_tokens": 16000
                },
                system="You are a JSON-generating assistant. You must ONLY output valid, parseable JSON with no additional text or formatting.",
                messages=[
                    {"role": "user", "content": prompt + "\n\nIMPORTANT: Your response MUST be a valid JSON object with the exact structure shown in the example above. Do not include any explanatory text, markdown formatting, or code blocks. Return only the raw JSON object."}
                ],
                timeout=600  # 10-minute timeout
            )
        else:
            response = client.messages.create(
                model=actual_model,
                max_tokens=4096,
                system="You are a JSON-generating assistant. You must ONLY output valid, parseable JSON with no additional text or formatting.",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                timeout=300  # 5-minute timeout
            )
        
        try:
            # Extract the text content
            if is_thinking_mode:
                # For thinking mode, we need to extract only the text content blocks
                response_text = ''.join(block.text for block in response.content if block.type == "text")
                
                # Store thinking content in session state for debugging/transparency (optional)
                thinking_content = ''.join(block.thinking for block in response.content if block.type == "thinking")
                if thinking_content:
                    st.session_state['last_thinking_content'] = thinking_content
            else:
                # Standard handling for regular responses
                response_text = response.content[0].text
            
            # Check for and fix common JSON formatting issues
            if is_claude_3_7:
                # Sometimes Claude 3.7 adds trailing commas which are invalid in JSON
                response_text = response_text.replace(",\n  ]", "\n  ]").replace(",\n]", "\n]")
                
                # Sometimes it adds comments which are invalid in JSON
                response_text = re.sub(r'//.*?\n', '\n', response_text)
            
            # Check if the JSON is complete (should end with a closing brace)
            if not response_text.strip().endswith('}'):
                raise json.JSONDecodeError("Incomplete JSON response", response_text, len(response_text))
                
            # Parse the JSON string
            dread_assessment = json.loads(response_text)
            return dread_assessment
        except (json.JSONDecodeError, IndexError, AttributeError) as e:
            # Create a fallback response with a proper DREAD structure
            fallback_assessment = {
                "Risk Assessment": [
                    {
                        "Threat Type": "Error",
                        "Scenario": f"Failed to parse Claude response: {str(e)}",
                        "Damage Potential": 0,
                        "Reproducibility": 0,
                        "Exploitability": 0,
                        "Affected Users": 0,
                        "Discoverability": 0
                    }
                ]
            }
            return fallback_assessment
    except Exception as e:
        # Handle timeout and other errors
        error_message = str(e)
        st.error(f"Error with Anthropic API: {error_message}")
        
        # Create a fallback response for timeout or other errors
        fallback_assessment = {
            "Risk Assessment": [
                {
                    "Threat Type": "Error",
                    "Scenario": f"API Error: {error_message}",
                    "Damage Potential": 0,
                    "Reproducibility": 0,
                    "Exploitability": 0,
                    "Affected Users": 0,
                    "Discoverability": 0
                }
            ]
        }
        return fallback_assessment

# Function to get DREAD risk assessment from LM Studio Server response.
def get_dread_assessment_lm_studio(lm_studio_endpoint, model_name, prompt):
    client = OpenAI(
        base_url=f"{lm_studio_endpoint}/v1",
        api_key="not-needed"  # LM Studio Server doesn't require an API key
    )

    # Define the expected response structure
    dread_schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "dread_assessment_response",
            "schema": {
                "type": "object",
                "properties": {
                    "Risk Assessment": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "Threat Type": {"type": "string"},
                                "Scenario": {"type": "string"},
                                "Damage Potential": {"type": "integer", "minimum": 1, "maximum": 10},
                                "Reproducibility": {"type": "integer", "minimum": 1, "maximum": 10},
                                "Exploitability": {"type": "integer", "minimum": 1, "maximum": 10},
                                "Affected Users": {"type": "integer", "minimum": 1, "maximum": 10},
                                "Discoverability": {"type": "integer", "minimum": 1, "maximum": 10}
                            },
                            "required": ["Threat Type", "Scenario", "Damage Potential", "Reproducibility", "Exploitability", "Affected Users", "Discoverability"]
                        }
                    }
                },
                "required": ["Risk Assessment"]
            }
        }
    }

    response = client.chat.completions.create(
        model=model_name,
        response_format=dread_schema,
        messages=[
            {"role": "system", "content": "You are a helpful assistant designed to output JSON."},
            {"role": "user", "content": prompt}
        ]
    )

    # Convert the JSON string in the 'content' field to a Python dictionary
    try:
        dread_assessment = json.loads(response.choices[0].message.content)
    except json.JSONDecodeError:
        # Handle error silently
        dread_assessment = {}
    
    return dread_assessment

# Function to get DREAD risk assessment from the Groq model's response.
def get_dread_assessment_groq(groq_api_key, groq_model, prompt):
    client = Groq(api_key=groq_api_key)
    response = client.chat.completions.create(
        model=groq_model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "You are a helpful assistant designed to output JSON."},
            {"role": "user", "content": prompt}
        ]
    )

    # Process the response using our utility function
    reasoning, dread_assessment = process_groq_response(
        response.choices[0].message.content,
        groq_model,
        expect_json=True
    )
    
    # If we got reasoning, display it in an expander in the UI
    if reasoning:
        with st.expander("View model's reasoning process", expanded=False):
            st.write(reasoning)

    return dread_assessment