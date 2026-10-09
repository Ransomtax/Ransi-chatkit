(function () {
  if (window.__ransiWidgetStarted) return;
  console.log("RANSI: SCRIPT ESEGUITO");
  window.__ransiWidgetStarted = true;

  function createRansiWidget() {
    if (!document.body) {
      window.__ransiWidgetStarted = false;
      return;
    }

    if (document.getElementById("ransi-launcher-wrap")) return;

    var avatar = "https://ransi-chatkit.onrender.com/public/Ransi-optimized.webp";
    var domainKey = "domain_pk_6ac7c094233081908b37464b6a704e440ffdbccbf67ff780";

    var style = document.createElement("style");
    style.textContent = `
      #ransi-launcher-wrap {
        position:fixed;right:24px;bottom:24px;z-index:999999;
        display:flex;flex-direction:column;align-items:center;gap:6px;
        font-family:Montserrat,Arial,sans-serif;
      }
      #ransi-launcher {
        width:78px;height:78px;border:0;border-radius:50%;padding:0;
        cursor:pointer;background:#07589B;overflow:hidden;
        box-shadow:0 8px 25px rgba(7,88,155,.35);
      }
      #ransi-launcher img {
        display:block;width:100%;height:100%;object-fit:cover;
      }
      #ransi-label {
        border:0;background:#07589B;color:#fff;padding:6px 12px;
        border-radius:20px;font:600 12px Montserrat,Arial,sans-serif;
        cursor:pointer;
      }
      #ransi-chat {
        position:fixed;right:24px;bottom:24px;width:390px;height:650px;
        z-index:999998;background:#fff;border-radius:20px;
        box-shadow:0 12px 45px rgba(0,0,0,.22);overflow:hidden;
        font-family:Montserrat,Arial,sans-serif;
      }
      #ransi-chat[hidden] {display:none!important}
      #ransi-chat .ransi-header {
        height:82px;display:flex;align-items:center;padding:0 18px;
        background:#fff;border-bottom:1px solid #eee;
      }
      #ransi-chat .ransi-avatar {
        width:54px;height:54px;border-radius:50%;object-fit:cover;
      }
      #ransi-chat .ransi-info {margin-left:12px;flex:1}
      #ransi-chat .ransi-name {
        font-size:18px;font-weight:700;color:#575756;
      }
      #ransi-chat .ransi-subtitle {
        margin-top:3px;font-size:13px;color:#575756;
      }
      #ransi-chat .ransi-close {
        border:0;background:transparent;font-size:30px;line-height:1;
        color:#575756;cursor:pointer;
      }
      #ransi-chat .ransi-body {
        height:calc(100% - 82px);overflow:hidden;
      }
      #ransi-chat openai-chatkit {
        display:block;width:100%;height:100%;
      }
      @media(max-width:600px) {
        #ransi-chat {
          right:10px;bottom:10px;width:calc(100vw - 20px);
          height:calc(100vh - 20px);border-radius:16px;
        }
        #ransi-launcher-wrap {right:16px;bottom:16px}
      }
    `;
    document.head.appendChild(style);

    var wrap = document.createElement("div");
    wrap.id = "ransi-launcher-wrap";
    wrap.innerHTML =
      '<button id="ransi-launcher" aria-label="Chiedi a Ransi">' +
      '<img src="' + avatar + '" alt="Ransi"></button>' +
      '<button id="ransi-label" type="button">Chiedi a Ransi</button>';
    document.body.appendChild(wrap);

    var chat = document.createElement("div");
    chat.id = "ransi-chat";
    chat.hidden = true;
    chat.innerHTML =
      '<div class="ransi-header">' +
      '<img class="ransi-avatar" src="' + avatar + '" alt="Ransi">' +
      '<div class="ransi-info"><div class="ransi-name">Ransi</div>' +
      '<div class="ransi-subtitle">Assistente Ransomtax</div></div>' +
      '<button class="ransi-close" id="ransi-close" aria-label="Chiudi">×</button>' +
      '</div><div class="ransi-body">' +
      '<openai-chatkit id="ransi"></openai-chatkit></div>';
    document.body.appendChild(chat);

    function openRansi() {
      chat.hidden = false;
      wrap.style.display = "none";
    }

    function closeRansi() {
      chat.hidden = true;
      wrap.style.display = "flex";
    }

    document.getElementById("ransi-launcher")
      .addEventListener("click", openRansi);
    document.getElementById("ransi-label")
      .addEventListener("click", openRansi);
    document.getElementById("ransi-close")
      .addEventListener("click", closeRansi);

    function initChatKit() {
      var el = document.getElementById("ransi");
      if (!el || typeof el.setOptions !== "function") return;

      el.setOptions({
        api: {
          url: "https://ransi-chatkit.onrender.com/chatkit",
          domainKey: domainKey
        },
        theme: {
          colorScheme: "light",
          color: {
            accent: { primary: "#07589B", level: 1 }
          },
          typography: { fontFamily: "'Montserrat', sans-serif" },
          radius: "round"
        },
        startScreen: { greeting: "Come posso aiutarti?" }
      });
    }

    function loadChatKit() {
      if (customElements.get("openai-chatkit")) {
        initChatKit();
        return;
      }

      var script = document.createElement("script");
      script.src =
        "https://cdn.platform.openai.com/deployments/chatkit/chatkit.js";
      script.onload = function () {
        customElements.whenDefined("openai-chatkit").then(initChatKit);
      };
      script.onerror = function () {
        console.error("Ransi: caricamento di ChatKit non riuscito.");
      };
      document.head.appendChild(script);
    }

    loadChatKit();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", createRansiWidget, {
      once: true
    });
  } else {
    createRansiWidget();
  }
})();
