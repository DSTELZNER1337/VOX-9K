/* f32le-framed-v1 validation, independent of the DOM and neural engine. */
class VoxPcmParser {
    constructor() {
        this.pending = new Uint8Array(0);
        this.index = 0;
        this.ended = false;
    }
    push(bytes) {
        if (this.ended && bytes.length) throw new Error('Audio data after end frame.');
        const combined = new Uint8Array(this.pending.length + bytes.length);
        combined.set(this.pending); combined.set(bytes, this.pending.length);
        this.pending = combined;
        const frames = [];
        while (this.pending.length >= 16) {
            const view = new DataView(this.pending.buffer, this.pending.byteOffset, this.pending.byteLength);
            const size = view.getUint32(0, true), rate = view.getUint32(4, true);
            const index = view.getUint32(8, true), flags = view.getUint32(12, true);
            if (size > 4 * 1024 * 1024 || rate !== 24000 || index !== this.index ||
                ![0, 1, 2].includes(flags) || (flags === 0 && (!size || size % 4)) ||
                (flags === 1 && size !== 0)) throw new Error('Invalid Qwen audio frame.');
            if (this.pending.length < 16 + size) break;
            const payload = this.pending.slice(16, 16 + size);
            this.pending = this.pending.slice(16 + size);
            this.index++;
            if (flags === 2) throw new Error(new TextDecoder().decode(payload) || 'Qwen generation failed.');
            if (flags === 1) {
                this.ended = true;
                if (this.pending.length) throw new Error('Audio data after end frame.');
                break;
            }
            const sampleView = new DataView(payload.buffer);
            const samples = new Float32Array(size / 4);
            for (let i = 0; i < samples.length; i++) {
                samples[i] = sampleView.getFloat32(i * 4, true);
                if (!Number.isFinite(samples[i])) throw new Error('Invalid PCM sample.');
            }
            frames.push({samples, sampleRate: rate});
        }
        return frames;
    }
    finish() {
        if (!this.ended || this.pending.length) throw new Error('Qwen audio stream ended unexpectedly.');
    }
}
