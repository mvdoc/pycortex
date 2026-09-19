var mriview = (function(module) {

    //Fetch a binary payload (one of the three tractogram buffers) as an
    //ArrayBuffer. Same XMLHttpRequest style as surfload.js / CTMLoader.js.
    function loadBuffer(url, callback, errback) {
        var xhr = new XMLHttpRequest();
        xhr.onreadystatechange = function() {
            if (xhr.readyState == 4) {
                if (xhr.status == 200 || xhr.status == 206 || xhr.status == 0) {
                    callback(xhr.response);
                } else {
                    console.error("mriview.Tractogram: couldn't load " + url +
                                  " (" + xhr.status + ")");
                    if (errback !== undefined)
                        errback(xhr.status);
                }
            }
        };
        xhr.open("GET", url, true);
        xhr.responseType = "arraybuffer";
        xhr.send(null);
    }

    //Three.js r69 only enables 32-bit element indices when the
    //OES_element_index_uint extension is present (see the THREE.Line branch of
    //renderBufferDirect, three.js:20451, which picks UNSIGNED_INT purely from
    //the array type -- an unsupported extension means a GL error rather than a
    //fallback). Without it we duplicate the vertices instead, which also avoids
    //needing r69's `geometry.offsets` drawcall chunking for >65535 vertices.
    module.supportsUint32Index = function(renderer) {
        var gl = null;
        if (renderer !== undefined && renderer !== null)
            gl = renderer.context;
        else if (window.viewer !== undefined && window.viewer.renderer !== undefined)
            gl = window.viewer.renderer.context;

        if (gl === null || gl === undefined)
            return false;
        try {
            return !!gl.getExtension("OES_element_index_uint");
        } catch (e) {
            return false;
        }
    };

    //A bundle of streamlines, rendered as GL_LINES.
    //
    //`meta` is one entry of the `tracts` dict of the metadata package built by
    //cortex/webgl/data.py: {subject, n_points, n_streamlines, alpha, linewidth,
    //visible, color, groups, description, urls:{points, offsets, colors}}.
    module.Tractogram = function(name, meta, renderer) {
        this.name = name;
        this.meta = meta;
        this.renderer = renderer;

        this._visible = (meta.visible === undefined) ? true : !!meta.visible;
        this._opacity = (meta.alpha === undefined) ? 1 : meta.alpha;
        this._mix = 0;

        this.n_points = 0;
        this.n_streamlines = 0;
        this.geometry = null;
        this.material = null;
        this.line = null;

        //The viewer's own `loaded` Deferred must NOT wait on this one: tracts
        //are an overlay on top of a viewer that is usable without them.
        this.loaded = $.Deferred();

        this.object = new THREE.Group();
        this.object.name = "Tractogram:" + name;
        this.object.visible = this._visible;
        //Passes that render the scene with a surface-specific override
        //material (the SVG label depth pass in svgoverlay.js) must skip us:
        //those shaders expect surface attributes this geometry doesn't have.
        this.object.userData.skipOverrideMaterial = true;

        this.ui = new jsplot.Menu();
        this.ui.add({
            visible: {action:[this, "setVisible"]},
            opacity: {action:[this, "setOpacity", 0, 1]},
        });

        var buffers = {}, names = ["points", "offsets", "colors"];
        var pending = names.length;
        var failed = false;
        var ondone = function(bufname) {
            return function(data) {
                buffers[bufname] = data;
                if (--pending === 0 && !failed)
                    this._build(buffers);
            }.bind(this);
        }.bind(this);
        var onfail = function(status) {
            if (!failed) {
                failed = true;
                this.loaded.reject(status);
            }
        }.bind(this);

        for (var i = 0; i < names.length; i++)
            loadBuffer(meta.urls[names[i]], ondone(names[i]), onfail);
    };

    //Turn the three raw buffers into a THREE.Line of segments.
    module.Tractogram.prototype._build = function(buffers) {
        var points = new Float32Array(buffers.points);
        var offsets = new Uint32Array(buffers.offsets);
        var rawcolors = new Uint8Array(buffers.colors);

        var npts = points.length / 3;
        this.n_points = npts;
        //The offsets array carries a trailing sentinel equal to npts, so there
        //is one streamline per pair of consecutive entries.
        var nstream = Math.max(offsets.length - 1, 0);
        this.n_streamlines = nstream;

        //r69 always uploads vertex attributes as gl.FLOAT (three.js:20276
        //hardcodes it in setupVertexAttributes), so the uint8 colors must be
        //expanded to normalized floats -- normalized uint8 attributes are not
        //an option in this version.
        var colors = new Float32Array(rawcolors.length);
        for (var i = 0; i < rawcolors.length; i++)
            colors[i] = rawcolors[i] / 255;

        //Number of segments: every streamline of L points yields L-1 segments.
        var nseg = 0;
        for (var s = 0; s < nstream; s++)
            nseg += Math.max(offsets[s+1] - offsets[s] - 1, 0);

        var geometry = new THREE.BufferGeometry();
        if (module.supportsUint32Index(this.renderer) || npts <= 65535) {
            var index = new Uint32Array(2 * nseg);
            //Uint16 is enough (and universally supported) for small tractograms
            if (npts <= 65535)
                index = new Uint16Array(2 * nseg);
            var k = 0;
            for (var s = 0; s < nstream; s++) {
                for (var j = offsets[s]; j + 1 < offsets[s+1]; j++) {
                    index[k++] = j;
                    index[k++] = j + 1;
                }
            }
            geometry.addAttribute("position", new THREE.BufferAttribute(points, 3));
            geometry.addAttribute("color", new THREE.BufferAttribute(colors, 3));
            geometry.addAttribute("index", new THREE.BufferAttribute(index, 1));
        } else {
            //Fallback: duplicate the endpoints of every segment so no element
            //index buffer is needed at all.
            var pos = new Float32Array(6 * nseg);
            var col = new Float32Array(6 * nseg);
            var k = 0;
            for (var s = 0; s < nstream; s++) {
                for (var j = offsets[s]; j + 1 < offsets[s+1]; j++) {
                    for (var d = 0; d < 3; d++) {
                        pos[6*k + d] = points[3*j + d];
                        pos[6*k + 3 + d] = points[3*(j+1) + d];
                        col[6*k + d] = colors[3*j + d];
                        col[6*k + 3 + d] = colors[3*(j+1) + d];
                    }
                    k++;
                }
            }
            geometry.addAttribute("position", new THREE.BufferAttribute(pos, 3));
            geometry.addAttribute("color", new THREE.BufferAttribute(col, 3));
        }
        geometry.computeBoundingSphere();

        var alpha = this._opacity;
        var material = new THREE.LineBasicMaterial({
            vertexColors: THREE.VertexColors,
            transparent: alpha < 1,
            opacity: alpha,
            //Opaque tracts write depth so they occlude each other correctly;
            //translucent ones must not, or the draw order shows through.
            depthWrite: alpha >= 1,
            linewidth: (this.meta.linewidth === undefined) ? 1 : this.meta.linewidth,
        });

        this.geometry = geometry;
        this.material = material;
        this.line = new THREE.Line(geometry, material, THREE.LinePieces);
        this.line.name = "Tractogram:" + this.name + ":lines";
        this.object.add(this.line);

        this.loaded.resolve(this);
    };

    //Getter/setter pair, in the shape jsplot.Menu expects (called with no
    //argument it returns the current value, so dat.gui can initialize itself).
    module.Tractogram.prototype.setVisible = function(value) {
        if (value === undefined)
            return this._visible;
        this._visible = !!value;
        this._updateVisible();
    };

    module.Tractogram.prototype.setOpacity = function(value) {
        if (value === undefined)
            return this._opacity;
        this._opacity = value;
        if (this.material !== null) {
            this.material.opacity = value;
            this.material.transparent = value < 1;
            this.material.depthWrite = value >= 1;
            this.material.needsUpdate = true;
        }
    };

    //Streamlines are defined in the fiducial (unmorphed) space, so they only
    //make sense while the surface is not inflating/flattening.
    module.Tractogram.prototype.setMix = function(mix) {
        if (mix === undefined)
            return this._mix;
        this._mix = mix;
        this._updateVisible();
    };

    module.Tractogram.prototype._updateVisible = function() {
        this.object.visible = this._visible && this._mix === 0;
    };

    module.Tractogram.prototype.dispose = function() {
        if (this.line !== null)
            this.object.remove(this.line);
        if (this.geometry !== null)
            this.geometry.dispose();
        if (this.material !== null)
            this.material.dispose();
        this.geometry = null;
        this.material = null;
        this.line = null;
    };

    return module;
}(mriview || {}));
