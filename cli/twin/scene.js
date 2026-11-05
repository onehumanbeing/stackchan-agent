// The dashboard's 3D view: procedural StackChan (model.js) posed from the live state, nicer than accurate.
// Body variants: "simple" (two shoulder servos) and "full" (r7 arms from model/r7.json).  Chosen server-side.
import * as THREE from "three";
import {OrbitControls} from "three/addons/controls/OrbitControls.js";
import {RoomEnvironment} from "three/addons/environments/RoomEnvironment.js";
import {STLLoader} from "three/addons/loaders/STLLoader.js";
import {build} from "./model.js";

const rad = d => d * Math.PI / 180;
const view = document.getElementById("twin");
const renderer = new THREE.WebGLRenderer({antialias: true});
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.25;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
view.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0d0d0d);
scene.fog = new THREE.Fog(0x0d0d0d, 420, 900);
scene.environment = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture;
const key = new THREE.DirectionalLight(0xffffff, 2.2);
key.position.set(120, 260, 180); key.castShadow = true;
key.shadow.mapSize.set(2048, 2048); key.shadow.radius = 6;
Object.assign(key.shadow.camera, {left: -160, right: 160, top: 160, bottom: -160, near: 10, far: 700});
scene.add(key, new THREE.HemisphereLight(0xffffff, 0x202020, 0.4));
const rim = new THREE.DirectionalLight(0x9fb6ff, 0.8); rim.position.set(-200, 120, -160); scene.add(rim);
const floor = new THREE.Mesh(new THREE.CircleGeometry(600, 64), new THREE.MeshStandardMaterial({color: 0x161616, roughness: 0.9}));
floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; scene.add(floor);

const camera = new THREE.PerspectiveCamera(32, 1, 1, 3000);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;

// Live face on the screen: the robot's own screen grab, refreshed twice a second.
const screenMat = new THREE.MeshBasicMaterial({color: 0xffffff, toneMapped: false});
const loader = new THREE.TextureLoader();
setInterval(() => loader.load("/face.jpg?" + Date.now(), t => {
  t.colorSpace = THREE.SRGBColorSpace;
  const old = screenMat.map; screenMat.map = t; screenMat.needsUpdate = true; if (old) old.dispose();
}), 500);

const bot = build(screenMat);
window.twin = {scene, camera, controls, bot, full: () => full};   // handy from the browser console
scene.add(bot.root);

// Full body: r7 arm meshes (robot frame z up, x forward) re-based into this frame (y up, z forward).
let full = {left: new THREE.Group(), right: new THREE.Group(), ready: false};
async function loadFull() {
  const {meshes, cfg} = await fetch("/model.json").then(r => r.json());
  const stl = new STLLoader(), P = new THREE.Matrix4().set(0, 1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 0, 0, 1);
  full.cfg = cfg; full.parts = {};
  for (const m of meshes) {
    if (m.frame === "robot") continue;
    const geo = stl.parse(Uint8Array.from(atob(m.stl), c => c.charCodeAt(0)).buffer); geo.computeVertexNormals();
    const mesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({color: m.color, roughness: .5}));
    mesh.castShadow = mesh.receiveShadow = true; mesh.matrixAutoUpdate = false;
    const side = m.frame.startsWith("left") ? "left" : "right";
    full[side].add(mesh); (full.parts[m.frame] = full.parts[m.frame] || []).push(mesh);
  }
  const OUT = 36;   // r7 arm link sits inside its face plane; push it out to clear the 54 mm head
  for (const side of ["left", "right"]) {   // shoulder of the r7 frame onto this model's shoulder pivot
    const s = side === "left" ? 1 : -1, g = full[side];
    g.matrixAutoUpdate = false;
    const pv = bot.shoulders[side].pivot.position;
    g.matrix.copy(new THREE.Matrix4().makeTranslation(pv.x, pv.y, pv.z).multiply(P)
      .multiply(new THREE.Matrix4().makeTranslation(0, s * (OUT - cfg.armFaceY), -cfg.shoulderZ)));
    bot.shoulders[side].pivot.parent.add(g);
  }
  full.ready = true;
}

function poseFull(j) {
  const c = full.cfg, M4 = a => new THREE.Matrix4().set(...a), mul = (...ms) => ms.reduce((a, b) => a.clone().multiply(b));
  const armM = (s, phi) => { const co = Math.cos(rad(phi)), n = Math.sin(rad(phi));
    return new THREE.Matrix4().set(n, -s * co, 0, 0, 0, 0, s, s * c.armFaceY, -co, -s * n, 0, c.shoulderZ, 0, 0, 0, 1); };
  const shaft = d => new THREE.Matrix4().makeTranslation(c.shaftX, 0, 0).multiply(new THREE.Matrix4().makeRotationZ(rad(d)))
    .multiply(new THREE.Matrix4().makeTranslation(-c.shaftX, 0, 0));
  const lA = armM(1, j.ls), lH = mul(lA, M4(c.handL)), lW = mul(lH, shaft(j.le), M4(c.seatDW)),
        lG = mul(lW, shaft(j.lw), M4(c.seatWG)), lJ = mul(lG, shaft(j.lj));
  const rA = armM(-1, j.rs), rH = mul(rA, M4(c.handR)), rJ = mul(rH, shaft(j.rj));
  const F = {left_arm: lA, left_hand: lH, left_wrist: lW, left_grip: lG, left_jaw: lJ, right_arm: rA, right_hand: rH, right_grip: rH, right_jaw: rJ};
  for (const [f, list] of Object.entries(full.parts)) for (const m of list) m.matrix.copy(F[f]);
}

// State from the dashboard (SSE): servo degrees, head degrees, body variant, calibration.
const target = {ls: 0, le: 0, lw: 0, lj: 0, rs: 0, rj: 0, yaw: 0, pitch: 0}, shown = {...target};
let body = "simple", online = {left: false, right: false};
window.twinUpdate = s => {
  const cal = s.calibration || {joints: {}, head: {}};
  if ((s.body || "simple") !== body) frame(s.body || "simple");
  body = s.body || "simple";
  for (const [id, sv] of Object.entries(s.servos || {})) {
    const j = cal.joints[id];
    if (j) target[j.joint] = j.sign * (sv.deg - j.zero);
  }
  online = {left: !!(s.servos || {})[1], right: !!(s.servos || {})[5]};
  const h = s.head || {}, hc = cal.head || {};
  if (h.yaw != null) target.yaw = (hc.yaw_sign ?? 1) * (h.yaw - (hc.yaw_zero ?? 0));
  if (h.pitch != null) target.pitch = (hc.pitch_sign ?? 1) * (h.pitch - (hc.pitch_zero ?? 0));
  if (body === "full" && !full.ready && !full.loading) { full.loading = true; loadFull(); }
};

// Framing per body, seen from 45 degrees off the front (the full arms reach ~20 cm forward).
function frame(b) {
  const far = b === "full", d = far ? 560 : 360, t = new THREE.Vector3(0, far ? 90 : 80, far ? 60 : 0);
  controls.target.copy(t);
  camera.position.set(t.x + d * Math.SQRT1_2, t.y + d * 0.42, t.z + d * Math.SQRT1_2);
}

frame("simple");

function resize() { const w = view.clientWidth, h = view.clientHeight; renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix(); }
addEventListener("resize", resize); resize();
(function loop() {
  for (const k in shown) shown[k] += (target[k] - shown[k]) * 0.25;
  bot.yaw.rotation.y = rad(shown.yaw);
  bot.pitch.rotation.x = -rad(shown.pitch);
  for (const [side, j] of [["left", "ls"], ["right", "rs"]]) {
    const sh = bot.shoulders[side], isFull = body === "full" && full.ready;
    sh.simple.visible = online[side] && !isFull;
    sh.pivot.rotation.x = -rad(shown[j]);
    if (full.ready) full[side].visible = online[side] && isFull;
  }
  if (body === "full" && full.ready) {
    const h = full.cfg.presets.home;
    poseFull({ls: h.ls + shown.ls, le: shown.le, lw: shown.lw, lj: shown.lj, rs: h.rs + shown.rs, rj: shown.rj});
  }
  controls.update(); renderer.render(scene, camera); requestAnimationFrame(loop);
})();
