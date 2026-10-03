// ==========================================
// 3DVIEW.JS — Visualizador 3D do Palco (estilo QLC+)
// Consome Lumina.stage.fixtures e anima Pan/Tilt/Cor em tempo real.
// Requer THREE (three.min.js via CDN, carregado no index.html).
// ==========================================

(function () {
    const Lumina = window.Lumina = window.Lumina || {};

    const PAN_RANGE_DEG = 540;   // curso típico de moving head
    const TILT_RANGE_DEG = 220;
    const BEAM_LENGTH = 7;
    const LERP_SPEED = 0.18;     // suavização por frame

    const viz = {
        active: false,
        ready: false,
        scene: null, camera: null, renderer: null,
        fixtures: {},   // id -> { group, yoke, head, beamMesh, spot, state, target }
        container: null,
        _raf: null,
        _cam: { azimuth: 0, elevation: 0.45, dist: 11, target: null },
    };
    Lumina.viz3d = viz;

    function isMoving(f) {
        const t = (f.type || '').toUpperCase();
        return t.includes('MOVING') || t.includes('SPOT') || t.includes('BEAM') || t.includes('WASH') || !t.includes('PAR');
    }

    // Bounds adaptativos: os dados reais do palco.json podem estar em qualquer escala
    // (ex: x≈14 após arrastos no mapa 2D). Normalizamos para a cena.
    // Convenção do palco.json: x/y = planta (posição no chão), z = altura (0=chão, 3=aéreo).
    let bounds = { minX: -3, maxX: 3, minY: 0, maxY: 5 };

    function computeBounds(list) {
        if (!list.length) return;
        const xs = list.map(f => (f.position && f.position.x) || 0);
        const ys = list.map(f => (f.position && f.position.y) || 0);
        bounds = {
            minX: Math.min(...xs), maxX: Math.max(...xs),
            minY: Math.min(...ys), maxY: Math.max(...ys),
        };
        // Evita divisão por zero quando todas estão alinhadas
        if (bounds.maxX - bounds.minX < 0.001) { bounds.minX -= 1; bounds.maxX += 1; }
        if (bounds.maxY - bounds.minY < 0.001) { bounds.minY -= 1; bounds.maxY += 1; }
    }

    function stagePos(f) {
        const p = f.position || { x: 0, y: 0, z: 0 };
        
        // Proteção contra divisão por zero e posições muito foradas
        const dX = (bounds.maxX - bounds.minX) || 1;
        const dY = (bounds.maxY - bounds.minY) || 1;
        
        const nx = (p.x - bounds.minX) / dX; // 0..1
        const ny = (p.y - bounds.minY) / dY; // 0..1
        
        const sceneX = (nx - 0.5) * 8;            // largura útil: -4..4
        const sceneZ = -4 + (ny * 4);             // profundidade: -4..0 (trás pra frente)
        
        let sceneY = 0.15; // chão da pista
        if (sceneZ < -1) sceneY = 0.65; // em cima do palco
        if ((p.z || 0) > 1) sceneY = 4.05; // pendurado no truss

        return new THREE.Vector3(sceneX, sceneY, sceneZ);
    }

    viz.init = function (containerId) {
        if (viz.ready) return true;
        if (typeof THREE === 'undefined') {
            if (typeof showToast === 'function') showToast('Three.js não carregou (sem internet?). Visão 3D indisponível.', 'error');
            return false;
        }
        const container = document.getElementById(containerId);
        if (!container) return false;
        viz.container = container;

        viz.scene = new THREE.Scene();
        viz.scene.background = new THREE.Color(0x05060a);
        viz.scene.fog = new THREE.FogExp2(0x05060a, 0.03);

        const w = container.clientWidth || 600;
        const h = container.clientHeight || 400;
        viz.camera = new THREE.PerspectiveCamera(55, w / h, 0.1, 200);
        viz._cam.target = new THREE.Vector3(0, 1.5, 0);

        viz.renderer = new THREE.WebGLRenderer({ antialias: true });
        viz.renderer.setSize(w, h);
        viz.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
        viz.renderer.outputEncoding = THREE.sRGBEncoding; // IMPORTANTE: Corrige iluminação escura do PBR
        viz.renderer.shadowMap.enabled = true;
        viz.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
        viz.renderer.toneMapping = THREE.ACESFilmicToneMapping;
        viz.renderer.toneMappingExposure = 1.1;
        container.appendChild(viz.renderer.domElement);

        // --- Post-processing: Bloom (glow real nas lentes e feixes) ---
        // Os scripts examples/js expõem THREE.EffectComposer etc. Se algum CDN
        // falhar, seguimos sem bloom (fallback = renderer direto).
        viz.composer = null;
        if (THREE.EffectComposer && THREE.RenderPass && THREE.UnrealBloomPass) {
            viz.composer = new THREE.EffectComposer(viz.renderer);
            viz.composer.setSize(w, h);
            viz.composer.addPass(new THREE.RenderPass(viz.scene, viz.camera));
            const bloom = new THREE.UnrealBloomPass(
                new THREE.Vector2(w, h),
                0.9,   // strength: intensidade do glow
                0.55,  // radius: espalhamento suave
                0.25   // threshold: só o que é brilhante floresce
            );
            viz.composer.addPass(bloom);
            viz.bloomPass = bloom;
            // O composer ignora o outputEncoding do renderer; corrigimos com gamma pass
            if (THREE.ShaderPass && THREE.GammaCorrectionShader) {
                viz.composer.addPass(new THREE.ShaderPass(THREE.GammaCorrectionShader));
            }
        }
        
        // Adiciona um aviso na tela para explicar a sincronização do Patch/Mapa 2D
        const info = document.createElement('div');
        info.style.position = 'absolute';
        info.style.bottom = '10px';
        info.style.left = '10px';
        info.style.color = '#88a';
        info.style.fontSize = '12px';
        info.style.pointerEvents = 'none';
        info.innerHTML = "💡 Para adicionar luzes ou movê-las, use a Visão 2D e o Patch Fixtures.<br>As mudanças sincronizam automaticamente aqui!";
        container.appendChild(info);

        // Piso do palco + grid (áreas: palco / pista / aéreo)
        const floor = new THREE.Mesh(
            new THREE.PlaneGeometry(14, 10),
            new THREE.MeshStandardMaterial({ color: 0x14161c, roughness: 0.55, metalness: 0.25 })
        );
        floor.rotation.x = -Math.PI / 2;
        floor.receiveShadow = true;
        viz.scene.add(floor);

        const grid = new THREE.GridHelper(14, 14, 0x00f0ff, 0x22252e);
        grid.material.transparent = true;
        grid.material.opacity = 0.35;
        grid.position.y = 0.01;
        viz.scene.add(grid);

        // Fundo do palco (parede traseira)
        const wall = new THREE.Mesh(
            new THREE.PlaneGeometry(14, 6),
            new THREE.MeshStandardMaterial({ color: 0x0b0d12, roughness: 1 })
        );
        wall.position.set(0, 3, -5);
        wall.receiveShadow = true;
        viz.scene.add(wall);

        // Palco (plataforma elevada encostada na parede)
        const stagePlatform = new THREE.Mesh(
            new THREE.BoxGeometry(8, 0.6, 4),
            new THREE.MeshStandardMaterial({ color: 0x1a1c23, roughness: 0.45, metalness: 0.15 })
        );
        stagePlatform.position.set(0, 0.3, -3); // Profundidade vai de -5 a -1
        stagePlatform.castShadow = true;
        stagePlatform.receiveShadow = true;
        viz.scene.add(stagePlatform);

        // Truss em "U" saindo da parede (Baseado no seu Bar real!)
        const trussMat = new THREE.MeshStandardMaterial({ color: 0x333844, metalness: 0.6, roughness: 0.4 });
        
        // Hastes Laterais saindo da parede
        const trussL = new THREE.Mesh(new THREE.BoxGeometry(0.15, 0.15, 4), trussMat);
        trussL.position.set(-3.5, 4.2, -3); // Z de -5 a -1
        
        const trussR = new THREE.Mesh(new THREE.BoxGeometry(0.15, 0.15, 4), trussMat);
        trussR.position.set(3.5, 4.2, -3);

        // Haste Frontal fechando o U
        const trussF = new THREE.Mesh(new THREE.BoxGeometry(7.15, 0.15, 0.15), trussMat);
        trussF.position.set(0, 4.2, -1);

        trussL.castShadow = trussR.castShadow = trussF.castShadow = true;
        viz.scene.add(trussL, trussR, trussF);

        viz.scene.add(new THREE.AmbientLight(0x404060, 0.7));
        viz.scene.add(new THREE.HemisphereLight(0x8899bb, 0x222233, 0.45)); // Preenchimento frio de casa noturna

        const key = new THREE.DirectionalLight(0x8899bb, 0.4);
        key.position.set(4, 8, 6);
        key.castShadow = true;
        key.shadow.mapSize.set(2048, 2048);
        key.shadow.camera.left = -8; key.shadow.camera.right = 8;
        key.shadow.camera.top = 8; key.shadow.camera.bottom = -8;
        key.shadow.bias = -0.0005;
        viz.scene.add(key);

        setupCameraControls(container);
        updateCamera();

        window.addEventListener('resize', viz.resize);
        viz.ready = true;
        return true;
    };

    // --- Controles de câmera e Drag & Drop das Fixtures ---
    function setupCameraControls(el) {
        let dragging = false, lastX = 0, lastY = 0;
        let dragFixture = null, dragPlane = null, dragOffset = new THREE.Vector3();

        el.addEventListener('mousedown', (e) => { 
            const rect = el.getBoundingClientRect();
            const mouse = new THREE.Vector2(
                ((e.clientX - rect.left) / rect.width) * 2 - 1,
                -((e.clientY - rect.top) / rect.height) * 2 + 1
            );
            const raycaster = new THREE.Raycaster();
            raycaster.setFromCamera(mouse, viz.camera);
            
            // Tenta pegar alguma fixture
            const interactables = Object.values(viz.fixtures).map(fx => fx.group);
            const intersects = raycaster.intersectObjects(interactables, true);
            
            if (intersects.length > 0) {
                let obj = intersects[0].object;
                while (obj && (!obj.userData || !obj.userData.fId)) obj = obj.parent;
                if (obj && obj.userData && obj.userData.fId) {
                    dragFixture = obj;
                    dragPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), -dragFixture.position.y);
                    if (raycaster.ray.intersectPlane(dragPlane, dragOffset)) {
                        dragOffset.sub(dragFixture.position);
                    } else {
                        dragOffset.set(0,0,0);
                    }
                    // Adiciona cursor de grab
                    el.style.cursor = 'grabbing';
                    return; // Interrompe mousedown da câmera
                }
            }

            // Se não clicou em fixture, orbita a câmera
            dragging = true; 
            lastX = e.clientX; 
            lastY = e.clientY; 
        });

        window.addEventListener('mouseup', () => { 
            dragging = false; 
            if (dragFixture) {
                el.style.cursor = 'default';
                // Salvar a nova posição no Backend
                const sceneX = dragFixture.position.x;
                const sceneZ = dragFixture.position.z;
                const sceneY = dragFixture.position.y;
                
                const nx = (sceneX / 8) + 0.5;
                const ny = (sceneZ + 4) / 4;
                
                const bs = window.Lumina && window.Lumina.stage && window.Lumina.stage.bounds ? window.Lumina.stage.bounds : {minX: -3, maxX: 3, minY: 0, maxY: 5};
                const dX = (bs.maxX - bs.minX) || 1;
                const dY = (bs.maxY - bs.minY) || 1;
                
                const pX = bs.minX + nx * dX;
                const pY = bs.minY + ny * dY;
                
                const fId = dragFixture.userData.fId;
                fetch('/api/update_position', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ id: fId, x: pX, y: pY, z: (sceneY > 2 ? 3 : 0) })
                });
                
                // Atualiza a memória local (para o 2D)
                if (window.Lumina && window.Lumina.stage && window.Lumina.stage.fixtures) {
                    const fix = window.Lumina.stage.fixtures.find(f => f.id === fId);
                    if (fix && fix.position) {
                        fix.position.x = pX;
                        fix.position.y = pY;
                        fix.position.z = sceneY > 2 ? 3 : 0;
                    }
                }
                dragFixture = null;
            }
        });

        window.addEventListener('mousemove', (e) => {
            if (dragFixture) {
                const rect = el.getBoundingClientRect();
                const mouse = new THREE.Vector2(
                    ((e.clientX - rect.left) / rect.width) * 2 - 1,
                    -((e.clientY - rect.top) / rect.height) * 2 + 1
                );
                const raycaster = new THREE.Raycaster();
                raycaster.setFromCamera(mouse, viz.camera);
                const target = new THREE.Vector3();
                if (raycaster.ray.intersectPlane(dragPlane, target)) {
                    dragFixture.position.x = target.x - dragOffset.x;
                    dragFixture.position.z = target.z - dragOffset.z;
                    
                    // Snap automático de altura: chão vs palco (se não for aéreo)
                    if (dragFixture.position.y < 2) {
                        const isStage = dragFixture.position.z < -1;
                        dragFixture.position.y = isStage ? 0.65 : 0.15;
                        dragPlane.constant = -dragFixture.position.y;
                    }
                }
                return;
            }

            if (!dragging || !viz.active) return;
            viz._cam.azimuth -= (e.clientX - lastX) * 0.006;
            viz._cam.elevation = Math.max(0.05, Math.min(1.4, viz._cam.elevation + (e.clientY - lastY) * 0.005));
            lastX = e.clientX; lastY = e.clientY;
            updateCamera();
        });

        el.addEventListener('wheel', (e) => {
            e.preventDefault();
            viz._cam.dist = Math.max(4, Math.min(30, viz._cam.dist + e.deltaY * 0.01));
            updateCamera();
        }, { passive: false });
    }

    function updateCamera() {
        const c = viz._cam;
        viz.camera.position.set(
            c.target.x + c.dist * Math.sin(c.azimuth) * Math.cos(c.elevation),
            c.target.y + c.dist * Math.sin(c.elevation),
            c.target.z + c.dist * Math.cos(c.azimuth) * Math.cos(c.elevation)
        );
        viz.camera.lookAt(c.target);
    }

    viz.resize = function () {
        if (!viz.ready || !viz.container) return;
        const w = viz.container.clientWidth, h = viz.container.clientHeight;
        if (w === 0 || h === 0) return;
        viz.camera.aspect = w / h;
        viz.camera.updateProjectionMatrix();
        viz.renderer.setSize(w, h);
        if (viz.composer) {
            viz.composer.setSize(w, h);
            if (viz.bloomPass) viz.bloomPass.setSize(w, h);
        }
    };

    // --- Construção das fixtures ---
    function buildFixture(f) {
        const group = new THREE.Group();
        group.userData = { fId: f.id }; // Para o Drag & Drop via Raycaster
        group.position.copy(stagePos(f));

        const bodyMat = new THREE.MeshStandardMaterial({ color: 0x22252e, metalness: 0.7, roughness: 0.35 });
        const moving = isMoving(f);

        let yoke = null, head = null;
        if (moving) {
            // Base + garfo (yoke, gira = pan) + cabeça (gira = tilt)
            const base = new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.12, 0.34), bodyMat);
            base.castShadow = true;
            group.add(base);

            yoke = new THREE.Group();
            yoke.position.y = -0.06;
            group.add(yoke);

            const armL = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.3, 0.1), bodyMat);
            armL.position.set(-0.16, -0.15, 0);
            const armR = armL.clone(); armR.position.x = 0.16;
            yoke.add(armL, armR);

            head = new THREE.Group();
            head.position.y = -0.28;
            yoke.add(head);

            const headMesh = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.14, 0.34, 16), bodyMat);
            headMesh.castShadow = true;
            head.add(headMesh);
        } else {
            // PAR: canhão fixo apontando pro palco
            head = new THREE.Group();
            const parMesh = new THREE.Mesh(new THREE.CylinderGeometry(0.14, 0.18, 0.3, 16), bodyMat);
            parMesh.castShadow = true;
            head.add(parMesh);
            group.add(head);
            // z alto = pendurado (feixe pra baixo, sem rotação); chão = feixe pra cima levemente inclinado
            const elevated = f.position && (f.position.z || 0) > 1;
            head.rotation.x = elevated ? 0 : Math.PI * 0.9;
        }

        // Lente emissiva (mostra a cor mesmo com dimmer baixo)
        const lensMat = new THREE.MeshBasicMaterial({ color: 0x111111 });
        const lens = new THREE.Mesh(new THREE.CircleGeometry(0.11, 16), lensMat);
        lens.position.y = -0.18;
        lens.rotation.x = Math.PI / 2;
        head.add(lens);

        // Feixe volumétrico em duas camadas: núcleo intenso (alimenta o Bloom)
        // + halo largo e suave (aponta pra -Y local)
        const beamGeo = new THREE.ConeGeometry(0.9, BEAM_LENGTH, 32, 1, true);
        beamGeo.translate(0, -BEAM_LENGTH / 2, 0);
        const beamMat = new THREE.MeshBasicMaterial({
            color: 0xffffff,
            transparent: true,
            opacity: 0.0,
            blending: THREE.AdditiveBlending,
            depthWrite: false,
            side: THREE.DoubleSide,
        });
        const beamMesh = new THREE.Mesh(beamGeo, beamMat);
        beamMesh.position.y = -0.17;
        head.add(beamMesh);

        const coreGeo = new THREE.ConeGeometry(0.35, BEAM_LENGTH * 0.92, 24, 1, true);
        coreGeo.translate(0, -BEAM_LENGTH * 0.92 / 2, 0);
        const coreMat = new THREE.MeshBasicMaterial({
            color: 0xffffff,
            transparent: true,
            opacity: 0.0,
            blending: THREE.AdditiveBlending,
            depthWrite: false,
            side: THREE.DoubleSide,
        });
        const coreMesh = new THREE.Mesh(coreGeo, coreMat);
        coreMesh.position.y = -0.17;
        head.add(coreMesh);

        // SpotLight real iluminando o piso (com sombra)
        // Sem castShadow por fixture: cada SpotLight com sombra é um shadow-map pass
        // extra por frame. Com várias fixtures isso derruba o FPS (causa do travamento).
        // A key light da cena já cobre as sombras principais do palco.
        const spot = new THREE.SpotLight(0xffffff, 0, 25, Math.PI / 10, 0.5, 1.2);
        spot.position.set(0, -0.17, 0);
        spot.castShadow = false;
        const spotTarget = new THREE.Object3D();
        spotTarget.position.set(0, -BEAM_LENGTH, 0);
        head.add(spotTarget);
        spot.target = spotTarget;
        head.add(spot);

        viz.scene.add(group);

        viz.fixtures[f.id] = {
            data: f, group, yoke, head, beamMesh, beamMat, coreMat, lensMat, spot, moving,
            state: { pan: 127, tilt: 127, r: 255, g: 255, b: 255, dimmer: 0 },
            target: { pan: 127, tilt: 127, r: 255, g: 255, b: 255, dimmer: 0 },
            _col: new THREE.Color(), // buffer reutilizável (evita alocar por frame)
        };
    }

    viz.refresh = async function () {
        if (!viz.ready) return;
        // Limpa fixtures antigas
        Object.values(viz.fixtures).forEach(fx => viz.scene.remove(fx.group));
        viz.fixtures = {};
        const list = (Lumina.stage && Lumina.stage.fixtures.length)
            ? Lumina.stage.fixtures
            : (Lumina.stage ? await Lumina.stage.refresh() : []);
        computeBounds(list);
        list.forEach(buildFixture);
    };

    // --- API pública chamada pelo XY Pad e pelos eventos WebSocket ---
    viz.setPanTilt = function (id, pan, tilt) {
        const fx = viz.fixtures[id];
        if (!fx) return;
        fx.target.pan = pan;
        fx.target.tilt = tilt;
    };

    viz.setColor = function (id, r, g, b, dimmer) {
        const fx = viz.fixtures[id];
        if (!fx) return;
        fx.target.r = r; fx.target.g = g; fx.target.b = b;
        if (dimmer !== undefined) fx.target.dimmer = dimmer;
        else if (fx.target.dimmer === 0) fx.target.dimmer = 255;
    };

    viz.setChaseStep = function (ids, activeId, r, g, b) {
        (ids || []).forEach(id => viz.setColor(id, 0, 0, 0, 0));
        viz.setColor(activeId, r, g, b, 255);
    };

    viz.setAllColor = function (r, g, b) {
        Object.keys(viz.fixtures).forEach(id => viz.setColor(id, r, g, b));
    };

    viz.setAllDimmer = function (v) {
        Object.values(viz.fixtures).forEach(fx => fx.target.dimmer = v);
    };

    viz.blackout = function () {
        viz.setAllDimmer(0);
    };

    // --- Loop de animação ---
    function animate() {
        if (!viz.active) { viz._raf = null; return; }
        viz._raf = requestAnimationFrame(animate);

        Object.values(viz.fixtures).forEach(fx => {
            const s = fx.state, t = fx.target;
            ['pan', 'tilt', 'r', 'g', 'b', 'dimmer'].forEach(k => s[k] += (t[k] - s[k]) * LERP_SPEED);

            if (fx.moving && fx.yoke) {
                fx.yoke.rotation.y = THREE.MathUtils.degToRad((s.pan / 255 - 0.5) * PAN_RANGE_DEG);
                fx.head.rotation.x = THREE.MathUtils.degToRad((s.tilt / 255 - 0.5) * TILT_RANGE_DEG);
            }

            const intensity = s.dimmer / 255;
            const col = fx._col.setRGB(s.r / 255, s.g / 255, s.b / 255);
            fx.beamMat.color.copy(col);
            fx.beamMat.opacity = 0.10 * intensity;               // halo suave
            if (fx.coreMat) {
                fx.coreMat.color.copy(col);
                fx.coreMat.opacity = 0.28 * intensity;            // núcleo que floresce no bloom
            }
            // Lente com cor >1.0: estoura o threshold do bloom = glow real na fonte
            fx.lensMat.color.copy(col).multiplyScalar(Math.max(0.05, intensity * 2.5));
            fx.spot.color.copy(col);
            fx.spot.intensity = 2.6 * intensity;
        });

        if (viz.composer) viz.composer.render();
        else viz.renderer.render(viz.scene, viz.camera);
    }

    viz.start = function () {
        viz.active = true;
        viz.resize();
        if (!viz._raf) animate();
    };

    viz.stop = function () {
        viz.active = false;
    };
})();

// --- Toggle 2D / 3D no painel do mapa ---
let stage3dOn = false;
async function toggleStage3D() {
    const btn = document.getElementById('btnToggle3D');
    const map2d = document.getElementById('stageMap');
    const map3d = document.getElementById('stage3d');
    const viz = window.Lumina && Lumina.viz3d;
    if (!viz) return;

    if (!stage3dOn) {
        if (!viz.init('stage3d')) return; // Three.js indisponível
        map2d.style.display = 'none';
        map3d.style.display = 'block';
        stage3dOn = true;
        if (btn) btn.innerText = '🗺 Visão 2D';
        await viz.refresh();
        // Estado inicial: pinta com o último estado conhecido do engine, se disponível
        try {
            if (Lumina.stage && Lumina.stage.capture) await Lumina.stage.capture();
        } catch (e) { /* opcional */ }
        viz.start();
    } else {
        viz.stop();
        map3d.style.display = 'none';
        map2d.style.display = 'flex';
        stage3dOn = false;
        if (btn) btn.innerText = '🧊 Visão 3D';
        // Recarrega do backend para garantir que as posições arrastadas no 3D sejam refletidas!
        if (typeof loadStageMap === 'function') {
            setTimeout(loadStageMap, 50);
        }
    }
}
