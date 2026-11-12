"""three.js STL viewer markup (embedded in Streamlit and in the shareable HTML file)."""
from __future__ import annotations

import html

VIEWER_HTML = """
<style>
 html,body{margin:0;background:transparent;font-family:'Inter Tight',system-ui,sans-serif}
 #wrap{position:relative;width:100%;height:520px;border-radius:14px;overflow:hidden;
   background:radial-gradient(ellipse at 50% 30%,#1B1B1A 0%,#0B0B0A 80%);border:1px solid #2A2927}
 #bar{position:absolute;top:10px;right:10px;display:flex;gap:6px;z-index:5}
 #bar button{background:rgba(23,23,22,.92);color:#EDEBE6;border:1px solid #2A2927;font-family:inherit;
   border-radius:8px;padding:5px 10px;font-size:12px;cursor:pointer}
 #bar button:hover{border-color:#8C8880} #bar button.on{border-color:#6FA08E;color:#6FA08E;background:rgba(111,160,142,.1)}
 #hint{position:absolute;left:12px;bottom:10px;color:#8C8880;font-size:12px;z-index:5}
 #dims{position:absolute;left:12px;top:10px;color:#EDEBE6;font-size:12px;z-index:5;
   background:rgba(23,23,22,.92);padding:5px 10px;border-radius:8px;border:1px solid #2A2927}
</style>
<div id="wrap">
 <div id="dims">__DIMS__</div>
 <div id="bar"><button id="rot" class="on">Rotate</button><button id="wire">Wireframe</button><button id="reset">Reset view</button><button id="vr" style="display:none">Enter VR</button></div>
 <div id="hint">drag: rotate · scroll: zoom · right-drag: pan</div>
</div>
<script type="importmap">{"imports":{
 "three":"https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js",
 "three/addons/":"https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"}}</script>
<script type="module">
import * as THREE from "three";
import {OrbitControls} from "three/addons/controls/OrbitControls.js";
import {STLLoader} from "three/addons/loaders/STLLoader.js";
const el = document.getElementById("wrap");
const W = el.clientWidth, H = el.clientHeight;
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(38, W / H, 0.1, 100000);
const renderer = new THREE.WebGLRenderer({antialias: true, alpha: true});
renderer.setPixelRatio(window.devicePixelRatio); renderer.setSize(W, H); el.appendChild(renderer.domElement);
scene.add(new THREE.HemisphereLight(0xffffff, 0x2a2a28, 1.05));
const key = new THREE.DirectionalLight(0xffffff, 1.5); key.position.set(3, 5, 4); scene.add(key);
const rim = new THREE.DirectionalLight(0xffffff, 0.45); rim.position.set(-4, 2, -3); scene.add(rim);
const bin = atob("__B64__"); const buf = new Uint8Array(bin.length);
for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
const geo = new STLLoader().parse(buf.buffer); geo.computeVertexNormals(); geo.center();
const group = new THREE.Group(); group.rotation.x = -Math.PI / 2; scene.add(group);   // CAD Z-up -> three Y-up
const mat = new THREE.MeshStandardMaterial({color: 0xA7AFB2, metalness: 0.3, roughness: 0.5});
const mesh = new THREE.Mesh(geo, mat); group.add(mesh);
const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geo, 28), new THREE.LineBasicMaterial({color: 0x0a0a0a, transparent: true, opacity: .5}));
group.add(edges);
geo.computeBoundingBox(); geo.computeBoundingSphere();
const r = geo.boundingSphere.radius, bb = geo.boundingBox;
const grid = new THREE.GridHelper(r * 6, 24, 0x34332f, 0x222120);
grid.position.y = -(bb.max.z - bb.min.z) / 2 - r * 0.001; scene.add(grid);
const axes = new THREE.AxesHelper(r * 0.9); axes.position.set(-r * 1.4, grid.position.y, r * 1.4); axes.setColors(new THREE.Color(0xD27A52), new THREE.Color(0x8C8880), new THREE.Color(0x6FA08E)); scene.add(axes);
const home = new THREE.Vector3(r * 2.4, r * 1.7, r * 2.6);
camera.position.copy(home);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true; controls.dampingFactor = 0.08; controls.autoRotate = true; controls.autoRotateSpeed = 1.6;
controls.zoomSpeed = 0.35;                 // default 1.0 is far too twitchy on trackpads / fast wheels
controls.zoomToCursor = true;              // zoom toward what the mouse points at
controls.rotateSpeed = 0.7; controls.panSpeed = 0.6;
controls.minDistance = r * 0.8; controls.maxDistance = r * 10;   // can't lose the part
const rot = document.getElementById("rot"), wire = document.getElementById("wire");
rot.onclick = () => { controls.autoRotate = !controls.autoRotate; rot.classList.toggle("on", controls.autoRotate); };
wire.onclick = () => { mat.wireframe = !mat.wireframe; edges.visible = !mat.wireframe; wire.classList.toggle("on", mat.wireframe); };
document.getElementById("reset").onclick = () => { camera.position.copy(home); controls.target.set(0, 0, 0); };
renderer.domElement.addEventListener("pointerdown", () => { controls.autoRotate = false; rot.classList.remove("on"); });
// VR: headset sessions run in metres, so shrink the millimetre scene 1000x and float it at arm's length.
renderer.xr.enabled = true;
const vr = document.getElementById("vr");
if (navigator.xr && navigator.xr.isSessionSupported) {
  navigator.xr.isSessionSupported("immersive-vr").then(ok => { if (ok) vr.style.display = ""; }).catch(() => {});
}
vr.onclick = async () => {
  try {
    const session = await navigator.xr.requestSession("immersive-vr", {optionalFeatures: ["local-floor"]});
    session.addEventListener("end", () => { scene.scale.setScalar(1); scene.position.set(0, 0, 0); controls.enabled = true; });
    scene.scale.setScalar(0.001); scene.position.set(0, 1.2, -1.0); controls.enabled = false;
    await renderer.xr.setSession(session);
  } catch (e) { vr.textContent = "VR unavailable"; }
};
renderer.setAnimationLoop(() => { controls.update(); renderer.render(scene, camera); });
</script>
"""


def standalone_page(b64_stl: str, dims: str, prompt: str, volume: float) -> str:
    """A single self-contained HTML file (three.js loaded from a CDN) that anyone can open."""
    body = VIEWER_HTML.replace("__B64__", b64_stl).replace("__DIMS__", html.escape(dims))
    return (f"<!doctype html><html><head><meta charset=utf-8><title>Fillet model</title>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<link rel=stylesheet href='https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;600&display=swap'><style>body{margin:0;padding:32px 24px;background:#0E0E0D;color:#EDEBE6;font-family:'Inter Tight',system-ui,sans-serif}"
            "main{max-width:1000px;margin:auto}h1{font-size:1.5rem;font-weight:600;letter-spacing:-.02em;margin:0 0 4px}"
            "p{color:#8C8880;margin:4px 0 16px}</style></head><body><main>"
            f"<h1>Fillet model</h1><p>{html.escape(prompt)}</p>{body.replace('height:520px', 'height:70vh')}"
            f"<p>{html.escape(dims)} · volume {volume:,.0f} mm³ · drafted with Fillet</p></main></body></html>")
