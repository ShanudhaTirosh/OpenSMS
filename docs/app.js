// OpenSMS Documentation Interactive Logic
document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  initCodeTabs();
  initCopyButtons();
  initPlayground();
  initSearch();
  initActiveSidebarLink();
});

// 1. Theme Management (Light / Dark)
function initTheme() {
  const themeToggle = document.getElementById("themeToggle");
  const currentTheme = localStorage.getItem("opensms_theme") || "dark";
  document.documentElement.setAttribute("data-theme", currentTheme);
  updateThemeButtonText(currentTheme);

  if (themeToggle) {
    themeToggle.addEventListener("click", () => {
      const active = document.documentElement.getAttribute("data-theme");
      const next = active === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      localStorage.setItem("opensms_theme", next);
      updateThemeButtonText(next);
    });
  }
}

function updateThemeButtonText(theme) {
  const btn = document.getElementById("themeToggle");
  if (btn) {
    btn.innerHTML = theme === "dark" ? "☀️ Light" : "🌙 Dark";
  }
}

// 2. Multi-Language Code Tabs
function initCodeTabs() {
  const tabContainers = document.querySelectorAll(".code-container");
  tabContainers.forEach(container => {
    const tabs = container.querySelectorAll(".code-tab");
    const blocks = container.querySelectorAll("pre");

    tabs.forEach(tab => {
      tab.addEventListener("click", () => {
        const lang = tab.getAttribute("data-lang");
        tabs.forEach(t => t.classList.remove("active"));
        tab.classList.add("active");

        blocks.forEach(block => {
          if (block.getAttribute("data-lang") === lang) {
            block.style.display = "block";
          } else {
            block.style.display = "none";
          }
        });
      });
    });
  });
}

// 3. Copy to Clipboard
function initCopyButtons() {
  document.querySelectorAll(".copy-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const container = btn.closest(".code-container") || btn.closest(".interactive-output");
      const pre = container.querySelector("pre[style*='display: block'], pre:not([style*='display: none'])");
      if (pre) {
        navigator.clipboard.writeText(pre.innerText.trim()).then(() => {
          const original = btn.innerHTML;
          btn.innerHTML = "✓ Copied!";
          btn.style.color = "#10b981";
          setTimeout(() => {
            btn.innerHTML = original;
            btn.style.color = "";
          }, 2000);
        });
      }
    });
  });
}

// 4. Interactive API Playground & cURL Generator
function initPlayground() {
  const ipInput = document.getElementById("pgDeviceIp");
  const portInput = document.getElementById("pgPort");
  const keyInput = document.getElementById("pgApiKey");
  const numberInput = document.getElementById("pgNumber");
  const msgInput = document.getElementById("pgMessage");
  const simSelect = document.getElementById("pgSimSlot");

  const curlPre = document.getElementById("pgCurlOutput");
  const pythonPre = document.getElementById("pgPythonOutput");
  const nodePre = document.getElementById("pgNodeOutput");

  function updateSnippets() {
    if (!curlPre) return;

    const ip = (ipInput && ipInput.value.trim()) || "100.85.12.34";
    const port = (portInput && portInput.value.trim()) || "9292";
    const key = (keyInput && keyInput.value.trim()) || "osms_demo_key_77a9c";
    const number = (numberInput && numberInput.value.trim()) || "+1234567890";
    const text = (msgInput && msgInput.value.trim()) || "Hello from OpenSMS Gateway!";
    const simSlot = simSelect ? parseInt(simSelect.value, 10) : 0;

    const baseUrl = `http://${ip}:${port}`;

    // cURL
    const simParam = simSlot >= 0 ? `, \\"sim_slot\\": ${simSlot}` : "";
    const curlCode = `curl -i -X POST '${baseUrl}/sms/' \\\n  -H 'Content-Type: application/json' \\\n  -H 'Authorization: Bearer ${key}' \\\n  -d '{"number": "${number}", "text": "${text}"${simSlot >= 0 ? `, "sim_slot": ${simSlot}` : ""}}'`;
    curlPre.innerText = curlCode;

    // Python requests
    if (pythonPre) {
      const pythonCode = `import requests\n\nres = requests.post(\n    "${baseUrl}/sms/",\n    headers={"Authorization": "Bearer ${key}"},\n    json={\n        "number": "${number}",\n        "text": "${text}"${simSlot >= 0 ? `,\n        "sim_slot": ${simSlot}` : ""}\n    }\n)\nprint(res.json())`;
      pythonPre.innerText = pythonCode;
    }

    // Node.js
    if (nodePre) {
      const nodeCode = `const res = await fetch("${baseUrl}/sms/", {\n  method: "POST",\n  headers: {\n    "Content-Type": "application/json",\n    "Authorization": "Bearer ${key}"\n  },\n  body: JSON.stringify({\n    number: "${number}",\n    text: "${text}"${simSlot >= 0 ? `,\n    sim_slot: ${simSlot}` : ""}\n  })\n});\nconsole.log(await res.json());`;
      nodePre.innerText = nodeCode;
    }
  }

  const inputs = [ipInput, portInput, keyInput, numberInput, msgInput, simSelect];
  inputs.forEach(input => {
    if (input) {
      input.addEventListener("input", updateSnippets);
      input.addEventListener("change", updateSnippets);
    }
  });

  updateSnippets();
}

// 5. Client-Side Quick Search
function initSearch() {
  const searchInput = document.getElementById("docSearchInput");
  if (!searchInput) return;

  searchInput.addEventListener("input", (e) => {
    const query = e.target.value.toLowerCase().trim();
    const sections = document.querySelectorAll(".doc-section");

    sections.forEach(sec => {
      if (!query) {
        sec.style.display = "";
        return;
      }
      const text = sec.innerText.toLowerCase();
      if (text.includes(query)) {
        sec.style.display = "";
      } else {
        sec.style.display = "none";
      }
    });
  });
}

// 6. Highlight active sidebar link on scroll
function initActiveSidebarLink() {
  const links = document.querySelectorAll(".sidebar-link");
  const sections = document.querySelectorAll(".doc-section");

  window.addEventListener("scroll", () => {
    let currentId = "";
    sections.forEach(sec => {
      const top = sec.offsetTop - 120;
      if (window.scrollY >= top) {
        currentId = sec.getAttribute("id");
      }
    });

    links.forEach(link => {
      const href = link.getAttribute("href");
      if (href === `#${currentId}`) {
        link.classList.add("active");
      } else {
        link.classList.remove("active");
      }
    });
  });
}
