// Live 3D twin of the robot: the r7 CAD meshes (model/r7.json), joints driven by the streamed servo angles.
// Kinematics follow stackchan-desktop-robot/cad-gripper (assembly.py): shoulder -> hand -> elbow -> wrist -> jaw.
(async function () {
  const view = document.getElementById("twin");
  const [{meshes, cfg}, cal] = await Promise.all([fetch("/model.json").then(r => r.json()), fetch("/calibration.json").then(r => r.json())]);
  const renderer = new THREE.WebGLRenderer({antialias: true});
  renderer.setPixelRatio(window.devicePixelRatio);
  view.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0e0e0e);
  const camera = new THREE.PerspectiveCamera(35, 1, 1, 5000);
  camera.position.set(300, 200, 280);
  const controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.target.set(40, 70, 0);
  controls.enableDamping = true;
  scene.add(new THREE.HemisphereLight(0xffffff, 0x444444, 0.8));
  const sun = new THREE.DirectionalLight(0xffffff, 0.7); sun.position.set(200, 400, 250); scene.add(sun);
  const root = new THREE.Group(); root.rotation.x = -Math.PI / 2; scene.add(root);   // robot frame: z up
  const grid = new THREE.GridHelper(600, 24, 0x333333, 0x222222); grid.rotation.x = Math.PI / 2; grid.position.x = 80; root.add(grid);

  const loader = new THREE.STLLoader(), byFrame = {};
  for (const m of meshes) {
    const geo = loader.parse(Uint8Array.from(atob(m.stl), c => c.charCodeAt(0)).buffer); geo.computeVertexNormals();
    const mesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({color: m.color, roughness: .65, metalness: .05, side: THREE.DoubleSide}));
    mesh.matrixAutoUpdate = false; root.add(mesh);
    (byFrame[m.frame] = byFrame[m.frame] || []).push(mesh);
  }

  const M4 = a => new THREE.Matrix4().set(...a), rad = d => d * Math.PI / 180;
  const mul = (...ms) => ms.reduce((a, b) => a.clone().multiply(b));
  function armM(s, phi) {   // assembly.arm_in_robot
    const c = Math.cos(rad(phi)), n = Math.sin(rad(phi));
    return new THREE.Matrix4().set(n, -s * c, 0, 0, 0, 0, s, s * cfg.armFaceY, -c, -s * n, 0, cfg.shoulderZ, 0, 0, 0, 1);
  }
  function shaftM(deg) {    // assembly.about_shaft
    const t = new THREE.Matrix4().makeTranslation(cfg.shaftX, 0, 0);
    return t.multiply(new THREE.Matrix4().makeRotationZ(rad(deg))).multiply(new THREE.Matrix4().makeTranslation(-cfg.shaftX, 0, 0));
  }
  const home = cfg.presets.home, target = {...home}, shown = {...home};
  function pose(v) {
    const lA = armM(1, v.ls), lH = mul(lA, M4(cfg.handL)), lW = mul(lH, shaftM(v.le), M4(cfg.seatDW)),
          lG = mul(lW, shaftM(v.lw), M4(cfg.seatWG)), lJ = mul(lG, shaftM(v.lj));
    const rA = armM(-1, v.rs), rH = mul(rA, M4(cfg.handR)), rJ = mul(rH, shaftM(v.rj));
    const F = {robot: new THREE.Matrix4(), left_arm: lA, left_hand: lH, left_wrist: lW, left_grip: lG, left_jaw: lJ,
               right_arm: rA, right_hand: rH, right_grip: rH, right_jaw: rJ};
    for (const [f, list] of Object.entries(byFrame)) for (const m of list) m.matrix.copy(F[f]);
  }
  // Called by the dashboard with every state update: {servo id: {deg, ...}}.
  window.twinUpdate = servos => {
    for (const [id, s] of Object.entries(servos || {})) {
      const j = cal.joints[id];
      if (j) target[j.joint] = home[j.joint] + j.sign * (s.deg - j.zero);
    }
  };
  function resize() { const w = view.clientWidth, h = view.clientHeight; renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix(); }
  addEventListener("resize", resize); resize();
  (function loop() {
    for (const k in shown) shown[k] += (target[k] - shown[k]) * 0.35;   // smooth between 10 Hz updates
    pose(shown); controls.update(); renderer.render(scene, camera); requestAnimationFrame(loop);
  })();
})();
