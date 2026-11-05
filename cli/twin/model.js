// Procedural StackChan model (MIT, no external meshes): rounded head with a live screen, neck, a LEGO-style
// chassis with four 56 mm wheels, and two arm variants.  Units: mm, y up, robot faces +z.
import * as THREE from "three";
import {RoundedBoxGeometry} from "three/addons/geometries/RoundedBoxGeometry.js";

const mat = (color, rough = 0.55, metal = 0) => new THREE.MeshStandardMaterial({color, roughness: rough, metalness: metal});
export const M = {
  shell: mat(0xf2f2ee, 0.42), bezel: mat(0x141414, 0.35), grey: mat(0x6c7076, 0.5), dark: mat(0x2b2d31, 0.6),
  tire: mat(0x202020, 0.78), rim: mat(0x222222, 0.4, 0.2), servo: mat(0x161616, 0.45), beamW: mat(0xf4f4f4, 0.5),
  beamB: mat(0x1b1b1b, 0.5), pin: mat(0x2a6fd6, 0.4), yellow: mat(0xf2c230, 0.45),
};
const box = (w, h, d, r, m) => shadowed(new THREE.Mesh(new RoundedBoxGeometry(w, h, d, 3, r), m));
const cyl = (r, h, m, seg = 40) => shadowed(new THREE.Mesh(new THREE.CylinderGeometry(r, r, h, seg), m));
function shadowed(o) { o.castShadow = o.receiveShadow = true; return o; }
const at = (o, x, y, z) => { o.position.set(x, y, z); return o; };

// A LEGO Technic beam along x: rounded bar with pin holes every 8 mm.
function beam(holes, m) {
  const g = new THREE.Group(), len = holes * 8;
  g.add(box(len, 7.2, 7.2, 3.4, m));
  for (let i = 0; i < holes; i++) {
    const h = cyl(2.5, 7.6, M.bezel, 16); h.rotation.x = Math.PI / 2; h.position.x = -len / 2 + 4 + i * 8; g.add(h);
  }
  return g;
}

function wheel() {
  const g = new THREE.Group();
  const tire = cyl(28, 14, M.tire, 64); tire.rotation.z = Math.PI / 2; g.add(tire);
  for (let i = 0; i < 40; i++) {                                    // tread grooves
    const t = box(13, 1.2, 1.6, 0.5, M.tire), a = i / 40 * Math.PI * 2;
    t.position.set(0, Math.cos(a) * 28, Math.sin(a) * 28); t.rotation.x = -a; g.add(t);
  }
  const rim = cyl(18, 14.6, M.rim, 48); rim.rotation.z = Math.PI / 2; g.add(rim);
  for (let i = 0; i < 6; i++) {                                     // spokes
    const s = box(2, 30, 4, 1, M.beamB); s.rotation.x = i / 6 * Math.PI; s.position.x = 7.6; g.add(s);
  }
  const hub = cyl(5, 15.4, M.pin, 24); hub.rotation.z = Math.PI / 2; g.add(hub);
  return g;
}

// Head: 54 mm rounded cube; the screen is a plane whose texture the scene updates with the robot's face.
function head(screenMat) {
  const g = new THREE.Group();
  g.add(box(54, 54, 54, 6, M.shell));
  const bezel = box(50, 50, 2, 3, M.bezel); bezel.position.z = 26.6; g.add(bezel);
  const screen = new THREE.Mesh(new THREE.PlaneGeometry(40.6, 30.5), screenMat); screen.position.set(0, 2, 27.7); g.add(screen);
  const cam = cyl(1.6, 1, M.dark, 16); cam.rotation.x = Math.PI / 2; cam.position.set(0, 21, 27.7); g.add(cam);
  for (const s of [-1, 1]) {                                        // side pins that hold the arm adapters
    const p = cyl(3.5, 6, M.yellow, 20); p.rotation.z = Math.PI / 2; p.position.set(s * 29, 4, 0); g.add(p);
  }
  return g;
}

// Simple arm (two servos only): adapter disc, STS3215 body, a LEGO frame around it.
function simpleArm(side) {
  const g = new THREE.Group();
  const disc = cyl(10, 5, M.shell, 32); disc.rotation.z = Math.PI / 2; disc.position.x = side * 3; g.add(disc);
  const sv = box(24, 35, 45, 2, M.servo); sv.position.set(side * 18, 0, 10); g.add(sv);
  for (const y of [-21, 21]) { const b = beam(7, y < 0 ? M.beamB : M.beamW); b.rotation.y = Math.PI / 2; b.position.set(side * 18, y, 12); g.add(b); }
  for (const z of [-12, 36]) { const b = beam(6, M.beamB); b.rotation.z = Math.PI / 2; b.position.set(side * 31, 0, z); g.add(b); }
  return g;
}

// Joint tree: base (static) -> yaw -> pitch -> head + shoulders.  Returns the groups the scene animates.
export function build(screenMat) {
  const root = new THREE.Group();
  const chassis = new THREE.Group(); root.add(chassis);
  chassis.add(at(box(64, 16, 58, 4, M.dark), 0, 30, 0));
  for (const s of [-1, 1]) {
    const b = beam(9, M.beamW); b.rotation.y = Math.PI / 2; b.position.set(s * 35, 30, 0); chassis.add(b);
    for (const z of [-30, 30]) { const w = wheel(); w.position.set(s * 47, 28, z); chassis.add(w); }
  }
  const front = beam(5, M.beamB); front.position.set(0, 22, 33); chassis.add(front);
  const yaw = new THREE.Group(); yaw.position.y = 38; root.add(yaw);
  yaw.add(at(cyl(24, 6, M.grey, 48), 0, 3, 0));
  yaw.add(at(box(34, 16, 30, 3, M.grey), 0, 14, 0));
  const pitch = new THREE.Group(); pitch.position.y = 22; yaw.add(pitch);
  const h = head(screenMat); h.position.y = 30; pitch.add(h);
  const shoulders = {};
  for (const [side, key] of [[1, "left"], [-1, "right"]]) {        // robot's left = +x (faces +z)
    const s = new THREE.Group(); s.position.set(side * 32, 34, 0); pitch.add(s);
    const arm = simpleArm(side); s.add(arm);
    shoulders[key] = {pivot: s, simple: arm};
  }
  return {root, yaw, pitch, shoulders};
}
