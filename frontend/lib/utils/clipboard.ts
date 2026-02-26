/**
 * Utility for copying text to the clipboard with a fallback
 * for non-secure contexts (e.g. HTTP) where navigator.clipboard
 * is not available.
 */
export async function copyToClipboard(text: string): Promise<void> {
    // If we're in a secure context and the modern API is available
    if (navigator.clipboard && window.isSecureContext) {
        try {
            await navigator.clipboard.writeText(text);
            return;
        } catch (err) {
            console.warn('navigator.clipboard.writeText failed, falling back to execCommand', err);
        }
    }

    // Fallback for non-secure contexts (like testing on local network over HTTP)
    return new Promise((resolve, reject) => {
        const textArea = document.createElement("textarea");
        textArea.value = text;

        // Move textarea out of the viewport so it's not visible
        textArea.style.position = "absolute";
        textArea.style.left = "-999999px";
        textArea.style.top = "-999999px";
        textArea.setAttribute("readonly", "readonly"); // Prevent mobile keyboard from showing

        document.body.appendChild(textArea);
        textArea.select();

        try {
            const successful = document.execCommand('copy');
            if (successful) {
                resolve();
            } else {
                reject(new Error("document.execCommand('copy') failed or is unsupported"));
            }
        } catch (err) {
            reject(err);
        } finally {
            textArea.remove();
        }
    });
}
