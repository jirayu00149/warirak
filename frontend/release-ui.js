import{APP_RELEASE_LABEL,APP_VERSION}from'./release.js';
document.querySelectorAll('[data-app-version]').forEach(node=>{node.textContent=APP_RELEASE_LABEL;node.title='วารีรักษ์ '+APP_VERSION;});
