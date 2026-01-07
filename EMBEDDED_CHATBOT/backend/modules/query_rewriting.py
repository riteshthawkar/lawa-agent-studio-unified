import json
import os
from typing import List, Dict, Optional
from openai import AsyncOpenAI
from modules.config import logger, OPENAI_TIMEOUT

# Initialize OpenAI client
openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def format_categories_for_prompt(query_categories: Optional[List[Dict]]) -> str:
    """
    Format query categories into a prompt-friendly string for classification.

    Args:
        query_categories: List of category dicts with id, name, description, keywords

    Returns:
        Formatted string for inclusion in the agent prompt
    """
    if not query_categories:
        return ""

    category_lines = []
    for cat in query_categories:
        name = cat.get('name', '')
        description = cat.get('description', '')
        keywords = cat.get('keywords', [])

        line = f"- **{name}**"
        if description:
            line += f": {description}"
        if keywords:
            line += f" (keywords: {', '.join(keywords[:10])})"
        category_lines.append(line)

    return "\n".join(category_lines)


# Generate query agent prompt based on site context
def get_query_agent_prompt(site_domain=None, organization_name=None, query_categories=None, description=None, special_instructions=None, chatbot_name=None):
    """
    Generate query agent prompt for the given site/organization.

    Args:
        site_domain: Domain of the site (e.g., 'example.com')
        organization_name: Name of the organization (e.g., 'Example Corp')
        query_categories: List of category dicts for classification
        description: Description or purpose of the chatbot
        special_instructions: Special instructions for the chatbot
        chatbot_name: Name of the chatbot

    Returns:
        str: Query agent prompt customized for the site/organization
    """
    # Determine site/organization information
    if organization_name:
        org_reference = organization_name
        scope_reference = f"{organization_name}'s"
    elif site_domain:
        org_reference = site_domain
        scope_reference = f"{site_domain}'s"
    else:
        org_reference = "this organization"
        scope_reference = "the organization's"

    # Build context section
    context_section = ""
    if chatbot_name or description or special_instructions:
        context_section = "\n### ℹ️ CHATBOT IDENTITY & CONTEXT\n"
        if chatbot_name:
            context_section += f"- **Name:** {chatbot_name}\n"
        if description:
            context_section += f"- **Purpose/Description:** {description}\n"
        if special_instructions:
            context_section += f"- **Special Instructions:** {special_instructions}\n"
        context_section += "\n"

    # Build classification section if categories exist
    classification_section = ""
    categories_list = format_categories_for_prompt(query_categories)

    if categories_list:
        classification_section = f"""
5. **QUERY CLASSIFICATION**: You must classify the query into ONE of the predefined categories. Match the query intent to the most relevant category based on the category description and keywords.

**Available Categories:**
{categories_list}

If the query doesn't clearly match any category, classify it as "general" with low confidence.
"""
    else:
        classification_section = """
5. **QUERY CLASSIFICATION**: Since no predefined categories exist, classify the query into a general category based on intent:
   - "product_info" - Questions about products, services, offerings
   - "support" - Help requests, troubleshooting, issues
   - "pricing" - Cost, pricing, plans, billing questions
   - "general" - General inquiries, about us, contact
   - "technical" - Technical questions, specifications, implementation
   - "other" - Queries that don't fit other categories
"""

    return f"""You are an expert query analyzer for {org_reference} information system. Your primary goal is to refine user queries to optimize retrieval from two different vector indexes: a summary index and a text index, AND classify queries for analytics.

{context_section}### ⚠️ QUERY PROCESSING INSTRUCTIONS ⚠️

Your primary role is to optimize user queries for retrieval from {scope_reference} knowledge base. For any {org_reference}-related query, you should REWRITE it into specialized queries. Only use RESPOND for queries that are clearly unrelated to the organization.

**🚨 CRITICAL CONTEXT USAGE RULE:**
- **ALWAYS** analyze the conversation history to understand the current context
- **ALWAYS** incorporate specific context from previous messages into your queries (programs, people, departments, research areas, etc.)
- **ALWAYS** include relevant details from previous messages in both metadata and natural language queries
- **ALWAYS** use the conversation history to understand and incorporate context

You have THREE possible actions:

1.  **REWRITE**: This is the DEFAULT action for ANY query related to {org_reference}. You must generate **TWO** distinct queries:
    *   `metadata_query`: A query optimized for a **summary index**. This index contains documents with rich metadata fields like `document_title`, `document_summary`, and `keywords`. Your query should be a concise collection of keywords and phrases that are likely to appear in these metadata fields.
    *   `natural_language_query`: A query optimized for a **raw text index**. This should be a well-formed, natural language question that incorporates conversational context, resolves pronouns, and is as specific as possible.

2.  **Time-Sensitivity Analysis**: You must also determine if the query is time-sensitive. Look for keywords like "latest," "deadline," "when," "this year," or any phrasing that implies a need for current information.

3.  **RESPOND**: Only if the query is clearly out of scope (not related to {org_reference}) or is a general greeting.

4.  **IDENTITY**: If the query asks about who you are.

**IMPORTANT**: Do NOT use CLARIFY action. The main response generation agent will handle clarification based on retrieved documents. Your job is to always attempt to REWRITE queries to retrieve relevant information.

{classification_section}

---

### Hallucination Policy (Strict)

- Do NOT invent content, facts, or entities beyond what the user asked and the conversation history implies.
- If the user query is too ambiguous to produce useful specialized queries, choose `CLARIFY` rather than guessing.
- Keep outputs strictly within {org_reference} scope. Out-of-scope → use `RESPOND`.
- Your output must be valid JSON only; no extra text, commentary, or markdown.

--- 

### Query Rewriting Guidelines

**For `metadata_query` (Summary Index):**
*   **Goal**: Match the structured metadata.
*   **Format**: A string of keywords and key phrases. Do NOT use natural language.
*   **Process**: Extract key entities, topics, and intent from the user's query and conversation history. Synthesize these into a keyword-based query.
*   **CRITICAL**: Always include specific context from previous messages in your keywords (e.g., if previous message mentioned "Masters in Computer Vision", include "computer vision masters" in your keywords).
*   **Example**:
    *   User Query: "Tell me about the admission requirements for the computer vision master's program"
    *   `metadata_query`: "admission requirements computer vision master of science msc program eligibility application process"

**For `natural_language_query` (Text Index):**
*   **Goal**: Match the content of raw text chunks.
*   **Format**: A full, unambiguous question.
*   **Process**: Use the conversation history to resolve pronouns and add context. Expand abbreviations.
*   **CRITICAL**: Always incorporate specific context from previous messages (e.g., if previous message mentioned "Premium Consulting Services", include this in your query).
*   **Example**:
    *   User Query: "What about the requirements?" (after discussing premium services)
    *   `natural_language_query`: "What are the requirements for the Premium Consulting Services at {org_reference}?"

--- 

### JSON Output Format

Your output **MUST** be a valid JSON object.

**For REWRITE action:**
```json
{{
  "action": "rewrite",
  "is_time_sensitive": true,
  "rewritten_queries": {{
    "metadata_query": "...",
    "natural_language_query": "..."
  }},
  "classification": {{
    "category": "category_name",
    "confidence": 0.85
  }}
}}
```

**Classification Notes:**
- `category`: The category name that best matches the query intent
- `confidence`: A float between 0.0 and 1.0 indicating classification confidence
  - 0.9-1.0: Very confident match (query clearly matches category keywords/description)
  - 0.7-0.9: Good match (query aligns well with category)
  - 0.5-0.7: Moderate match (query somewhat relates to category)
  - Below 0.5: Weak match (use "general" or "other" instead)

**For RESPOND or IDENTITY actions:**
```json
{{
  "action": "respond",
  "response": "...",
  "classification": {{
    "category": "out_of_scope",
    "confidence": 1.0
  }}
}}
```

--- 

### Examples

**Example 1: Specific Query**
*   User Query: "What services do you offer?"
*   Analysis:
    ```json
    {{
      "action": "rewrite",
      "rewritten_queries": {{
        "metadata_query": "services offerings solutions programs {org_reference}",
        "natural_language_query": "What services and solutions are available at {org_reference}?"
      }}
    }}
    ```

**Example 2: Contextual Follow-up**
*   History: `[{{"role": "user", "content": "Tell me about your consulting services"}}]`
*   User Query: "Who are the team members?"
*   Analysis:
    ```json
    {{
      "action": "rewrite",
      "rewritten_queries": {{
        "metadata_query": "team members staff consultants consulting services {org_reference}",
        "natural_language_query": "Who are the team members in the consulting services at {org_reference}?"
      }}
    }}
    ```

**Example 2b: Service-Specific Follow-up (CRITICAL)**
*   History: `[{{"role": "user", "content": "What are the requirements for premium consulting?"}}, {{"role": "assistant", "content": "The requirements for premium consulting include..."}}]`
*   User Query: "What's included in the package?"
*   Analysis: User is asking about package contents, but context shows they're interested in premium consulting specifically
    ```json
    {{
      "action": "rewrite",
      "rewritten_queries": {{
        "metadata_query": "package contents features premium consulting services {org_reference}",
        "natural_language_query": "What's included in the premium consulting package at {org_reference}?"
      }}
    }}
    ```

**Example 3: Broad Query (REWRITE with general terms)**
*   User Query: "What are the admission requirements?"
*   Analysis: Broad query - rewrite to capture all admission requirements
    ```json
    {{
      "action": "rewrite",
      "is_time_sensitive": false,
      "rewritten_queries": {{
        "metadata_query": "admission requirements eligibility criteria application process programs",
        "natural_language_query": "What are the admission requirements for {org_reference} programs?"
      }}
    }}
    ```

**Example 4: Ambiguous Name (REWRITE to search for person)**
*   User Query: "Who is Fahad?"
*   Analysis: Name query - rewrite to search for this person in the organization's context
    ```json
    {{
      "action": "rewrite",
      "is_time_sensitive": false,
      "rewritten_queries": {{
        "metadata_query": "Fahad faculty staff student member",
        "natural_language_query": "Who is Fahad at {org_reference}? What is their role or position?"
      }}
    }}
    ```

**Example 4b: Another Broad Query (REWRITE to capture all programs)**
*   User Query: "Tell me about the programs"
*   Analysis: Broad query - rewrite to capture all program information
    ```json
    {{
      "action": "rewrite",
      "is_time_sensitive": false,
      "rewritten_queries": {{
        "metadata_query": "programs undergraduate graduate bachelor master PhD specializations",
        "natural_language_query": "What programs are available at {org_reference}?"
      }}
    }}
    ```

**Example 5: Time-Sensitive Query**
*   User Query: "What are the latest research papers from the organization?"
*   Analysis:
    ```json
    {{
      "action": "rewrite",
      "is_time_sensitive": true,
      "rewritten_queries": {{
        "metadata_query": "latest research papers publications 2024 2025",
        "natural_language_query": "What are the most recent research papers published by {org_reference}?"
      }}
    }}
    ```

**Example 6: Undergraduate Program Query**
*   User Query: "What GPA do I need for the undergraduate program?"
*   Analysis:
    ```json
    {{
      "action": "rewrite",
      "is_time_sensitive": false,
      "rewritten_queries": {{
        "metadata_query": "undergraduate bachelor BSc admission requirements GPA grade point average eligibility",
        "natural_language_query": "What GPA requirements are needed for admission to the undergraduate Bachelor of Science program at {org_reference}?"
      }}
    }}
    ```

**Example 7: Out of Scope**
*   User Query: "What's the weather like?"
*   Analysis:
    ```json
    {{
      "action": "respond",
      "response": "I can only answer questions related to {org_reference}. How can I help you with its products, services, or other matters?"
    }}
    ```

--- 

User query: {{query}}
Language: {{language}}
Previous messages: {{message_history}}

Your analysis:
"""

async def query_rewriting_agent(
    question: str,
    language: str,
    message_history: List[dict],
    site_domain: str = None,
    organization_name: str = None,
    query_categories: Optional[List[Dict]] = None,
    description: str = None,
    special_instructions: str = None,
    chatbot_name: str = None
) -> dict:
    """
    Processes the user's query to rewrite it into two specialized queries or provide a direct response.
    Also classifies the query into a category for analytics.

    Args:
        question: The user's question
        language: The language of the conversation
        message_history: Previous messages in the conversation
        site_domain: Domain of the site
        organization_name: Name of the organization
        query_categories: List of category dicts from Django backend for classification
        description: Description or purpose of the chatbot
        special_instructions: Special instructions for the chatbot
        chatbot_name: Name of the chatbot

    Returns a dictionary containing the action, relevant data, and classification:
    - For "rewrite": {
        "action": "rewrite",
        "rewritten_queries": {"metadata_query": str, "natural_language_query": str},
        "classification": {"category": str, "confidence": float}
      }
    - For "respond"/"identity": {
        "action": str,
        "response": str,
        "classification": {"category": str, "confidence": float}
      }
    """
    formatted_history = json.dumps(message_history) if message_history else "[]"
    query_agent_prompt = get_query_agent_prompt(
        site_domain, organization_name, query_categories, 
        description, special_instructions, chatbot_name
    )
    agent_prompt = query_agent_prompt.replace("{{query}}", question).replace("{{language}}", language).replace("{{message_history}}", formatted_history)

    # Default classification for fallback scenarios
    default_classification = {"category": "general", "confidence": 0.5}

    try:
        # Include the actual question in the user message for clarity
        user_message = f"""Analyze the following query and provide your analysis in the specified JSON format.

User Query: "{question}"
Language: {language}
Previous Messages: {formatted_history}"""
        
        completion = await openai_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": agent_prompt},
                {"role": "user", "content": user_message}
            ],
            temperature=0.1,
            top_p=1,
            response_format={"type": "json_object"},
            timeout=OPENAI_TIMEOUT,
        )
        result = json.loads(completion.choices[0].message.content)
        action = result.get("action", "rewrite")

        # Extract classification from result
        classification = result.get("classification", default_classification)
        if not isinstance(classification, dict):
            classification = default_classification
        # Ensure confidence is a valid float
        try:
            classification["confidence"] = float(classification.get("confidence", 0.5))
        except (TypeError, ValueError):
            classification["confidence"] = 0.5

        if action == "rewrite":
            rewritten_queries = result.get("rewritten_queries", {})
            return {
                "action": "rewrite",
                "is_time_sensitive": result.get("is_time_sensitive", False),
                "rewritten_queries": {
                    "metadata_query": rewritten_queries.get("metadata_query", question),
                    "natural_language_query": rewritten_queries.get("natural_language_query", question)
                },
                "final_query": rewritten_queries.get("natural_language_query", question),
                "classification": classification
            }
        elif action in ["respond", "identity"]:
            return {
                "action": action,
                "response": result.get("response", f"I can only answer questions related to {organization_name or site_domain or 'this organization'}."),
                "classification": {"category": "out_of_scope", "confidence": 1.0}
            }
        else:
            # Fallback for any unexpected action
            return {
                "action": "rewrite",
                "rewritten_queries": {"metadata_query": question, "natural_language_query": question},
                "final_query": question,
                "classification": default_classification
            }

    except Exception as e:
        logger.exception("Error in query rewriting agent:")
        # Fallback to using the original query for both indexes on error
        return {
            "action": "rewrite",
            "rewritten_queries": {"metadata_query": question, "natural_language_query": question},
            "final_query": question,
            "classification": default_classification
        }