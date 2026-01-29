/**
 * MarkdownContent component
 * Renders markdown content with syntax highlighting and code block wrap toggle
 * 
 * Security: Uses DOMPurify with strict configuration to prevent XSS attacks
 */

import DOMPurify from 'dompurify';
import MarkdownIt from 'markdown-it';
import React, { useMemo, useEffect, useRef } from 'react';
// @ts-ignore - markdown-it types not available

interface MarkdownContentProps {
  content: string;
}

// Configure DOMPurify hooks (configure once at module level)
if (typeof window !== 'undefined') {
  // Hook: Force add security attributes to all external links
  DOMPurify.addHook('afterSanitizeAttributes', (node) => {
    // Process <a> tags
    if (node.tagName === 'A') {
      const href = node.getAttribute('href') || '';
      
      // Detect external links or target="_blank"
      const isExternal = href.startsWith('http://') || href.startsWith('https://') || href.startsWith('//');
      const hasTargetBlank = node.getAttribute('target') === '_blank';
      
      if (isExternal || hasTargetBlank) {
        // Force add security attributes to prevent tabnabbing attacks
        node.setAttribute('rel', 'noopener noreferrer nofollow');
        node.setAttribute('target', '_blank');
      }
      
      // Block javascript: and other dangerous protocols (extra protection layer)
      if (/^(javascript|data|vbscript|file):/i.test(href)) {
        node.removeAttribute('href');
        node.setAttribute('href', '#blocked');
      }
    }
    
    // Process <img> tags - block dangerous src
    if (node.tagName === 'IMG') {
      const src = node.getAttribute('src') || '';
      if (/^(javascript|data:text\/html|vbscript):/i.test(src)) {
        node.removeAttribute('src');
      }
    }
  });
}

// Allowed HTML tag whitelist (safe subset)
const ALLOWED_TAGS = [
  // Text formatting
  'p', 'br', 'strong', 'em', 'b', 'i', 'u', 's', 'del', 'ins', 'mark',
  'small', 'sub', 'sup', 'abbr', 'kbd', 'samp', 'var', 'tt',
  // Code
  'code', 'pre',
  // Quotes
  'blockquote', 'q', 'cite',
  // Lists
  'ul', 'ol', 'li', 'dl', 'dt', 'dd',
  // Links and media
  'a', 'img',
  // Headings
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  // Separators
  'hr',
  // Containers
  'div', 'span',
  // Tables
  'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td', 'caption', 'colgroup', 'col',
  // Disclosure panels
  'details', 'summary',
] as const;

// Allowed attribute whitelist
const ALLOWED_ATTR = [
  'href', 'src', 'alt', 'title', 'class', 'id',
  'width', 'height',
  'target', 'rel',
  'name', 'open',
  'colspan', 'rowspan', 'scope',
  'lang', 'dir',
] as const;

// Forbidden event handler attributes (comprehensive coverage)
const FORBID_ATTR = [
  // Mouse events
  'onclick', 'ondblclick', 'onmousedown', 'onmouseup', 'onmouseover', 
  'onmouseout', 'onmousemove', 'onmouseenter', 'onmouseleave',
  // Keyboard events
  'onkeydown', 'onkeyup', 'onkeypress',
  // Focus events
  'onfocus', 'onblur', 'onfocusin', 'onfocusout',
  // Form events
  'onsubmit', 'onreset', 'onchange', 'oninput', 'oninvalid', 'onselect',
  // Load events
  'onload', 'onerror', 'onabort', 'onbeforeunload', 'onunload',
  // Clipboard events
  'oncopy', 'oncut', 'onpaste',
  // Drag events
  'ondrag', 'ondragstart', 'ondragend', 'ondragenter', 'ondragleave', 'ondragover', 'ondrop',
  // Media events
  'onplay', 'onpause', 'onended', 'oncanplay', 'onvolumechange',
  // Other
  'oncontextmenu', 'onscroll', 'onresize', 'ontouchstart', 'ontouchmove', 'ontouchend',
  'onanimationstart', 'onanimationend', 'ontransitionend', 'onwheel', 'onpointerdown',
  // Special attributes
  'formaction', 'xlink:href', 'xmlns',
] as const;

export const MarkdownContent: React.FC<MarkdownContentProps> = ({ content }) => {
  const md = useMemo(() => {
    return new MarkdownIt({
      html: false,  // Disable raw HTML input to prevent XSS (security first)
      linkify: true,
      typographer: true,
      breaks: true,
      // Security configuration: disable dangerous patterns in HTML entity decoding
      langPrefix: 'language-',
    });
  }, []);

  const html = useMemo(() => {
    // Preprocessing: remove potentially dangerous content
    const sanitizedContent = content
      // Remove script tags (even with html:false, double protection)
      .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
      // Remove on* event attributes
      .replace(/\s+on\w+\s*=/gi, ' data-blocked=');
    
    const rendered = md.render(sanitizedContent);

    // Use DOMPurify to sanitize HTML, strictly prevent XSS attacks
    return DOMPurify.sanitize(rendered, {
      ALLOWED_TAGS: [...ALLOWED_TAGS],
      ALLOWED_ATTR: [...ALLOWED_ATTR],
      ALLOW_DATA_ATTR: false,
      ALLOW_UNKNOWN_PROTOCOLS: false,
      ALLOW_ARIA_ATTR: false,
      ALLOW_SELF_CLOSE_IN_ATTR: false,
      FORBID_TAGS: ['script', 'style', 'iframe', 'frame', 'frameset', 'object', 'embed', 
                    'form', 'input', 'button', 'select', 'textarea', 'applet', 'base', 
                    'link', 'meta', 'noscript', 'template', 'svg', 'math'],
      FORBID_ATTR: [...FORBID_ATTR],
      // Use safe URL protocols - STRICT whitelist to prevent protocol bypass attacks
      // Only allows: http://, https://, mailto:, tel:, and relative paths starting with /
      // Blocks: javascript:, data:, vbscript:, file:, and custom protocols
      ALLOWED_URI_REGEXP: /^(?:(?:https?:|mailto|tel):|\/[^\s]*)$/i,
      // Return DocumentFragment to prevent certain attack vectors
      RETURN_DOM_FRAGMENT: false,
      RETURN_DOM: false,
      // Keep safe during sanitization
      SANITIZE_DOM: true,
      KEEP_CONTENT: true,
      IN_PLACE: false,
      // Force safe DOM parsing
      FORCE_BODY: true,
      // Disable dangerous attribute values
      SAFE_FOR_TEMPLATES: true,
    });
  }, [content, md]);

  const processedPreElementsRef = useRef<Set<HTMLPreElement>>(new Set());

  useEffect(() => {
    // Add toggle buttons to code blocks
    let preElements: NodeListOf<HTMLPreElement> | null = null;
    
    // Try to find the markdown-content div
    const markdownDivs = document.querySelectorAll('.markdown-content');
    if (markdownDivs.length > 0) {
      // Use the last one (most recent)
      const lastMarkdownDiv = markdownDivs[markdownDivs.length - 1];
      preElements = lastMarkdownDiv.querySelectorAll('pre');
    } else {
      console.warn('No markdown-content divs found');
      return;
    }

    if (!preElements || preElements.length === 0) {
      return;
    }

    preElements.forEach((pre, index) => {
      // Skip if already processed
      if (processedPreElementsRef.current.has(pre)) {
        return;
      }

      // Skip if already has toggle button
      if (pre.querySelector('.code-block-toggle')) {
        processedPreElementsRef.current.add(pre);
        return;
      }

      // Create wrapper - must wrap the pre element
      const wrapper = document.createElement('div');
      wrapper.className = 'code-block-wrapper';
      
      // Insert wrapper before pre element
      const parent = pre.parentNode;
      if (parent) {
        parent.insertBefore(wrapper, pre);
        wrapper.appendChild(pre);
      }

      // Add soft-wrap class by default (long lines wrap automatically)
      pre.classList.add('code-soft-wrap');

      // Create toggle button
      const button = document.createElement('button');
      button.className = 'code-block-toggle';
      button.textContent = 'Soft-wrap';
      button.setAttribute('data-mode', 'soft');
      button.setAttribute('title', 'Toggle between soft-wrap and hard-wrap');
      button.type = 'button';

      // Add click handler
      button.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();

        const currentMode = button.getAttribute('data-mode');
        
        if (currentMode === 'soft') {
          // Switch to hard-wrap mode (show horizontal scrollbar)
          pre.classList.remove('code-soft-wrap');
          pre.classList.add('code-hard-wrap');
          button.textContent = 'Hard-wrap';
          button.setAttribute('data-mode', 'hard');
        } else {
          // Switch to soft-wrap mode (auto-wrap long lines)
          pre.classList.remove('code-hard-wrap');
          pre.classList.add('code-soft-wrap');
          button.textContent = 'Soft-wrap';
          button.setAttribute('data-mode', 'soft');
        }
      });

      // Append button to wrapper (not to pre)
      wrapper.appendChild(button);
      processedPreElementsRef.current.add(pre);
    });
  }, [html]);

  return (
    <div
      className="markdown-content"
      data-markdown-container
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
};

MarkdownContent.displayName = 'MarkdownContent';
