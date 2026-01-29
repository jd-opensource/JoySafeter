import { GoogleGenAI } from "@google/genai";

import { ChatMessage } from "../types";

// Initialize the client
const ai = new GoogleGenAI({ apiKey: process.env.API_KEY });

// --- Existing Stream Method (Keep as is) ---
export const streamGeminiResponse = async (
  history: ChatMessage[],
  currentPrompt: string,
  onChunk: (text: string) => void,
  onComplete: () => void
) => {
  try {
    const contents = [
      ...history,
      { role: 'user', parts: [{ text: currentPrompt }] }
    ];

    // Fix: Using 'gemini-3-flash-preview' for basic text streaming tasks
    const model = 'gemini-3-flash-preview';

    const responseStream = await ai.models.generateContentStream({
      model: model,
      contents: contents as any,
      config: {
        systemInstruction: "You are a helpful AI assistant ",
      }
    });

    for await (const chunk of responseStream) {
      if (chunk.text) {
        onChunk(chunk.text);
      }
    }

    onComplete();

  } catch (error) {
    console.error("Error calling Gemini API:", error);
    onChunk("\n\n*Error: Failed to generate response. Please check your API key.*");
    onComplete();
  }
};

// --- Existing Text Gen Method (Keep as is) ---
export const generateGeminiResponse = async (
    prompt: string,
    systemInstruction: string = "You are a helpful assistant.",
    jsonMode: boolean = false
): Promise<string> => {
    try {
        const response = await ai.models.generateContent({
            // Fix: Using 'gemini-3-flash-preview' for general text generation
            model: 'gemini-3-flash-preview',
            contents: prompt,
            config: {
                systemInstruction: systemInstruction,
                responseMimeType: jsonMode ? "application/json" : "text/plain"
            }
        });
        return response.text || "";
    } catch (error) {
        console.error("Error generating content:", error);
        return "";
    }
};

// --- NEW: Graph Action Generator (The "God View" Engine) ---

import type { GraphAction, CopilotResponse } from '@/types/copilot'

// Re-export types for backward compatibility
export type { GraphAction, CopilotResponse }

export const generateGraphActions = async (
    userPrompt: string,
    graphContext: any
): Promise<CopilotResponse> => {
    try {
        // Find the last node to help with context positioning if needed
        const nodes = graphContext.nodes || [];
        const lastNode = nodes.length > 0 ? nodes[nodes.length - 1] : null;

        const contextStr = JSON.stringify({
            existingNodes: nodes.map((n: any) => ({ id: n.id, type: n.type, label: n.label, position: n.position })),
            lastNodePosition: lastNode?.position || { x: 0, y: 0 }
        }, null, 2);

        const systemPrompt = `
        You are an AI Agent Builder Copilot with "God Mode" access to a ReactFlow canvas.

        Your Goal: Help the user build, debug, or optimize their agent flow by executing ACTIONS.

        Current Graph Context:
        ${contextStr}

        Available Node Types: 'agent', 'condition', 'http', 'custom_function', 'direct_reply', 'human_input'.

        LAYOUT RULES (CRITICAL):
        1. **Compactness**: Keep the graph tight. Avoid long connecting lines.
        2. **Horizontal Flow**: The standard flow is Left-to-Right.
        3. **Spacing**:
           - **X Axis**: When connecting Node A -> Node B, place Node B exactly **350px** to the right of Node A. (e.g., if A.x is 100, B.x should be 450).
           - **Y Axis**: Keep aligned (Y offset 0) for main flow. If branching, offset Y by **150px**.
        4. **Start Point**: If the graph is empty, start at { x: 100, y: 100 }.
        5. **Continuation**: Always calculate the new node's position relative to the node you are connecting it to. Do NOT guess random coordinates like {x: 800, y: 800} if the previous node is at {x: 0, y: 0}.

        INSTRUCTIONS:
        1. Analyze the user's request and the current graph.
        2. If the user wants to modify the graph (add, connect, delete, config), generate a JSON plan.
        3. If the user just wants to chat, return an empty actions array.

        RESPONSE FORMAT (JSON ONLY):
        {
            "message": "I have added a translation node...",
            "actions": [
                {
                    "type": "CREATE_NODE",
                    "payload": {
                        "id": "generated_id",
                        "type": "agent",
                        "label": "Translator",
                        "position": { "x": 450, "y": 100 },
                        "config": { "systemPrompt": "Translate to Spanish" }
                    },
                    "reasoning": "Placing 350px to the right of the previous node"
                },
                {
                    "type": "CONNECT_NODES",
                    "payload": { "source": "existing_node_id", "target": "generated_id" },
                    "reasoning": "Connecting flow"
                }
            ]
        }
        `;

        const response = await ai.models.generateContent({
            // Fix: Using 'gemini-3-pro-preview' for complex reasoning/logic generation tasks
            model: 'gemini-3-pro-preview',
            contents: userPrompt,
            config: {
                systemInstruction: systemPrompt,
                responseMimeType: "application/json"
            }
        });

        if (!response.text) throw new Error("No response from AI");

        return JSON.parse(response.text) as CopilotResponse;

    } catch (error) {
        console.error("Graph Action Generation Failed:", error);
        return {
            message: "I encountered an error trying to process the graph actions. Please try again.",
            actions: []
        };
    }
};
