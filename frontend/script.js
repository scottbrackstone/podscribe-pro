const $ = (selector) => document.querySelector(selector)
const $$ = (selector) => Array.from(document.querySelectorAll(selector))
const PROFILE_KEY = "podscribe-voice-profile-v1"
const HISTORY_KEY = "podscribe-content-packs-v1"
const HISTORY_LIMIT = 20
const EXAMPLE_LIMIT = 8
const EXAMPLE_SEPARATOR = "\n---\n"
const INTERVIEW = [
    { question: "What are you learning or building right now? Explain it like you're texting a friend.", hint: "e.g. trying to get my podcast app to stop crashing when…" },
    { question: "What's something about AI or coding that excites you, and something that annoys you?", hint: "Say it how you'd say it out loud." },
    { question: "Tell me about a recent moment learning to code: a small win, or something that broke.", hint: "Real details make the best posts." },
    { question: "Who do you hope reads your posts, and what would you want them to think of you?", hint: "Other beginners? Devs a few years in? Future customers?" },
    { question: "What's a take on tech you have but haven't said out loud yet?", hint: "Doesn't need to be clever. Just honest." },
    { question: "What do posts you can't stand do? Anything you never want to sound like?", hint: "e.g. fake hype, 10-tip threads, ending everything with “thoughts?”" }
]

const state = { stance: "curious", transcript: "", angles: [], selectedAngle: null, models: [], variants: [], activeVariant: 0, platform: "instagram", fromHistory: false, historyId: null }
let historyTimer = null
let profileTimer = null

async function request(url, options = {}) {
    const response = await fetch(url, options)
    let data
    try { data = await response.json() } catch (_) { data = {} }
    if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`)
    return data
}

function profile() {
    return {
        bio: $("#profile-bio").value.trim(),
        guidance: $("#profile-guidance").value.trim(),
        avoid_phrases: $("#profile-avoid").value.split(",").map(x => x.trim().slice(0, 100)).filter(Boolean).slice(0, 20),
        examples: parseExamples($("#profile-examples").value),
        interview: $$(".interview-answer").map((field, i) => ({ question: INTERVIEW[i].question, answer: field.value.trim().slice(0, 1500) }))
    }
}

function parseExamples(text) {
    return text.split(/\n\s*-{3,}\s*\n/).map(x => x.trim().slice(0, 2200)).filter(Boolean).slice(0, EXAMPLE_LIMIT)
}

function sourceMetadata() {
    return { title: $("#source-title").value.trim(), creator: $("#source-creator").value.trim(), url: $("#source-url").value.trim(), credit: $("#source-credit").checked }
}

function commonPayload() {
    return { transcript: state.transcript, my_take: $("#my-take").value.trim(), source: sourceMetadata(), profile: profile(), stance: state.stance }
}

function setStatus(target, message, error = false) {
    target.textContent = message
    target.classList.toggle("error", error)
}

function setBusy(button, busy, label) {
    button.disabled = busy
    if (!button.dataset.label) button.dataset.label = button.textContent
    button.textContent = busy ? label : button.dataset.label
}

function saveProfile() {
    localStorage.setItem(PROFILE_KEY, JSON.stringify(profile()))
    $("#save-status").textContent = "Saved locally"
    renderVoiceMeter()
}

function scheduleProfileSave() {
    $("#save-status").textContent = "Saving…"
    clearTimeout(profileTimer)
    profileTimer = setTimeout(saveProfile, 400)
}

function renderInterview(saved) {
    const list = $("#interview-list"); list.innerHTML = ""
    INTERVIEW.forEach((item, i) => {
        const label = document.createElement("label"); label.className = "interview-item"
        const question = document.createElement("span"); question.textContent = item.question
        const field = document.createElement("textarea"); field.className = "interview-answer"; field.maxLength = 1500; field.placeholder = item.hint
        const match = saved.find(answer => answer.question === item.question)
        field.value = match ? match.answer : ""
        field.addEventListener("input", scheduleProfileSave)
        label.append(question, field); list.appendChild(label)
    })
}

function renderVoiceMeter() {
    const current = profile()
    const answered = current.interview.filter(item => item.answer.length >= 20).length
    const posted = current.examples.length
    // Interview answers get you started; real posted examples matter most.
    const score = Math.min(100, Math.round(answered / INTERVIEW.length * 60 + Math.min(posted, 5) / 5 * 40))
    const level = score >= 75 ? "Strong" : score >= 40 ? "Getting there" : score > 0 ? "Just started" : "Not set up"
    $("#voice-meter-fill").style.width = `${Math.max(score, 3)}%`
    $("#voice-meter-label").textContent = `Voice strength · ${level}`
    $("#voice-pill").textContent = `${answered}/${INTERVIEW.length} answered · ${posted} posted`
    return answered
}

function loadProfile() {
    let item = {}
    try { item = JSON.parse(localStorage.getItem(PROFILE_KEY) || "{}") } catch (_) { localStorage.removeItem(PROFILE_KEY) }
    $("#profile-bio").value = item.bio || ""
    $("#profile-guidance").value = item.guidance || ""
    $("#profile-avoid").value = (item.avoid_phrases || []).join(", ")
    $("#profile-examples").value = (item.examples || []).join(EXAMPLE_SEPARATOR)
    renderInterview(item.interview || [])
    // Open the voice setup until a couple of questions are answered.
    if (renderVoiceMeter() < 2) $("#voice-details").open = true
}

function addPostedExample(text, button) {
    const post = text.trim()
    if (!post) return
    const examples = [post, ...parseExamples($("#profile-examples").value).filter(item => item !== post)].slice(0, EXAMPLE_LIMIT)
    $("#profile-examples").value = examples.join(EXAMPLE_SEPARATOR)
    saveProfile()
    const old = button.textContent; button.textContent = "Saved to your voice ✓"; button.disabled = true
    setTimeout(() => { button.textContent = old; button.disabled = false }, 1800)
    setStatus($("#output-status"), "Nice. Future drafts will learn from the version you posted.")
}

function history() {
    try { return JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]") } catch (_) { return [] }
}

function saveCurrentPack() {
    const variant = state.variants[state.activeVariant]
    if (!variant) return
    const id = state.historyId || (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()))
    state.historyId = id
    const items = history().filter(item => item.id !== id)
    items.unshift({ id, date: new Date().toISOString(),
        angle: state.selectedAngle, source: sourceMetadata(), pack: structuredClone(variant.pack), generation: variant.generation })
    localStorage.setItem(HISTORY_KEY, JSON.stringify(items.slice(0, HISTORY_LIMIT)))
    renderHistory()
}

function scheduleHistorySave() {
    clearTimeout(historyTimer)
    historyTimer = setTimeout(saveCurrentPack, 500)
}

async function loadModels() {
    const select = $("#model-select"), compare = $("#compare-model")
    try {
        const data = await request("/clipwise/models")
        state.models = data.models
        for (const target of [select, compare]) {
            target.innerHTML = ""
            data.models.forEach(model => {
                const option = document.createElement("option")
                option.value = model.id; option.disabled = !model.enabled
                const price = model.input_price_per_million == null ? "" : ` · $${model.input_price_per_million}/$${model.output_price_per_million} per 1M`
                option.textContent = `${model.name}${price}${model.enabled ? "" : " · unavailable"}`
                option.title = model.reason || ""
                target.appendChild(option)
            })
            const preferred = data.models.find(m => m.id === data.default_model && m.enabled) || data.models.find(m => m.enabled)
            if (preferred) target.value = preferred.id
        }
        $("#model-note").textContent = data.warning || "Availability and pricing checked live via OpenRouter."
        refreshCompareModels()
    } catch (error) {
        select.innerHTML = "<option disabled>Models unavailable</option>"
        compare.innerHTML = ""
        $("#model-note").textContent = error.message
    }
}

async function findAngles() {
    const input = $("#source-input").value.trim(), button = $("#angle-button")
    if (!input) return setStatus($("#source-status"), "Paste a transcript or YouTube URL first.", true)
    setBusy(button, true, "Preparing the source…"); setStatus($("#source-status"), "Resolving transcript…")
    try {
        const resolved = await request("/transcript", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({source: input}) })
        state.transcript = resolved.transcript; state.fromHistory = false
        if (resolved.source_type === "youtube" && !$("#source-url").value) $("#source-url").value = input
        setStatus($("#source-status"), "Finding three grounded angles…")
        const data = await request("/clipwise/angles", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(commonPayload()) })
        state.angles = data.angles; state.selectedAngle = null; state.variants = []; state.historyId = null
        renderAngles(); setStatus($("#source-status"), "Choose the direction that feels most like you.")
    } catch (error) { setStatus($("#source-status"), error.message, true) }
    finally { setBusy(button, false) }
}

function renderAngles() {
    const list = $("#angle-list"); list.innerHTML = ""
    $("#angle-empty").classList.toggle("hidden", state.angles.length > 0)
    state.angles.forEach((angle, index) => {
        const card = document.createElement("article"); card.className = "angle-card"; card.tabIndex = 0
        const title = document.createElement("h3"), hook = document.createElement("p"), grounding = document.createElement("small")
        title.textContent = `${index + 1}. ${angle.title}`; hook.textContent = angle.hook; grounding.textContent = angle.grounding
        card.append(title, hook, grounding)
        const choose = () => { state.selectedAngle = angle; $$(".angle-card").forEach(x => x.classList.remove("active")); card.classList.add("active"); $("#pack-controls").classList.remove("hidden") }
        card.addEventListener("click", choose); card.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") choose() })
        list.appendChild(card)
    })
}

async function generatePack(model, compare = false) {
    if (!state.selectedAngle || !state.transcript) return
    const button = compare ? $("#compare-button") : $("#pack-button")
    setBusy(button, true, compare ? "Comparing…" : "Writing your pack…")
    setStatus($("#output-status"), "This usually takes under a minute.")
    try {
        const data = await request("/clipwise/pack", { method:"POST", headers:{"Content-Type":"application/json"},
            body: JSON.stringify({...commonPayload(), angle: state.selectedAngle, model}) })
        const variant = {pack:data.pack, generation:data.generation, preferred: state.variants.length === 0}
        if (compare) state.variants.push(variant); else state.variants = [variant]
        state.activeVariant = state.variants.length - 1
        $("#output-section").classList.remove("hidden"); renderOutput(); saveCurrentPack()
        $("#output-section").scrollIntoView({behavior:"smooth", block:"start"})
        setStatus($("#output-status"), "Pack ready. Every field is editable.")
    } catch (error) { setStatus($("#output-status"), error.message, true) }
    finally { setBusy(button, false) }
}

function refreshCompareModels() {
    const active = state.variants[state.activeVariant], select = $("#compare-model")
    Array.from(select.options).forEach(option => { option.hidden = Boolean(active && option.value === active.generation.model_id) })
    const next = Array.from(select.options).find(o => !o.hidden && !o.disabled); if (next) select.value = next.value
    $("#compare-button").disabled = !state.transcript || !next
}

function renderOutput() {
    const variant = state.variants[state.activeVariant]; if (!variant) return
    const meta = variant.generation, usage = meta.usage || {}, cost = meta.estimated_cost_usd == null ? "cost unavailable" : `$${meta.estimated_cost_usd.toFixed(4)} est.`
    $("#generation-meta").textContent = `${meta.model_name || meta.model_id} · ${(usage.total_tokens || 0).toLocaleString()} tokens · ${cost}`
    const tabs = $("#variant-tabs"); tabs.innerHTML = ""
    state.variants.forEach((item, index) => {
        const button = document.createElement("button"); button.className = index === state.activeVariant ? "active" : ""
        button.textContent = `${item.preferred ? "★ " : ""}${state.variants.length > 1 ? `Version ${index + 1}` : "Draft"}`
        button.title = item.generation.model_name || item.generation.model_id
        button.addEventListener("click", () => { state.activeVariant = index; renderOutput() }); tabs.appendChild(button)
    })
    if (state.variants.length > 1 && !variant.preferred) {
        const prefer = document.createElement("button"); prefer.textContent = "Mark preferred"
        prefer.addEventListener("click", () => { state.variants.forEach(v => v.preferred = false); variant.preferred = true; renderOutput(); saveCurrentPack() }); tabs.appendChild(prefer)
    }
    renderEditor(); refreshCompareModels()
}

function editorField(parent, heading, value, path, tall = false, limit = null, postable = false) {
    const section = document.createElement("div"); section.className = "editor-section"
    const head = document.createElement("div"); head.className = "editor-head"
    const title = document.createElement("h3"); title.textContent = heading
    const action = document.createElement("button"); action.className = "ghost compact"; action.textContent = "Copy"; action.addEventListener("click", () => copyText(field.value, action))
    const field = document.createElement("textarea"); field.value = value; field.dataset.path = path; if (tall) field.className = "tall"
    const counter = document.createElement("span"); counter.className = "counter"
    const updateCounter = () => { counter.textContent = limit ? `${field.value.length}/${limit}` : `${field.value.trim().split(/\s+/).filter(Boolean).length} words` }
    field.addEventListener("input", () => { setPath(state.variants[state.activeVariant].pack, path, field.value); updateCounter(); scheduleHistorySave() })
    const actions = document.createElement("div"); actions.className = "editor-actions"
    if (postable) {
        const posted = document.createElement("button"); posted.className = "ghost compact posted-button"; posted.textContent = "I posted this"
        posted.title = "Save your final version so future drafts sound more like you"
        posted.addEventListener("click", () => addPostedExample(field.value, posted)); actions.appendChild(posted)
    }
    actions.appendChild(action)
    head.append(title, actions); section.append(head, field, counter); updateCounter(); parent.appendChild(section)
}

function renderEditor() {
    const pack = state.variants[state.activeVariant].pack, root = $("#pack-editor"); root.innerHTML = ""
    if (state.platform === "instagram") {
        editorField(root, "Caption", pack.instagram.caption, "instagram.caption", true, null, true)
        editorField(root, "Hashtags", pack.instagram.hashtags.join(" "), "instagram.hashtags")
        const group = document.createElement("div"); group.className = "editor-section"
        const groupHead = document.createElement("div"); groupHead.className = "editor-head"
        const groupTitle = document.createElement("h3"); groupTitle.textContent = "Six-slide carousel"
        const groupCopy = document.createElement("button"); groupCopy.className = "ghost compact"; groupCopy.textContent = "Copy"
        groupCopy.addEventListener("click", () => copyText(pack.instagram.carousel.map(s => `Slide ${s.slide}: ${s.heading}\n${s.body}`).join("\n\n"), groupCopy))
        groupHead.append(groupTitle, groupCopy); group.appendChild(groupHead)
        pack.instagram.carousel.forEach((slide, i) => {
            const card = document.createElement("div"); card.className = "subcard"
            const label = document.createElement("strong"); label.textContent = `Slide ${i + 1}`
            const heading = document.createElement("input"); heading.value = slide.heading; heading.addEventListener("input", () => { slide.heading = heading.value; scheduleHistorySave() })
            const body = document.createElement("textarea"); body.value = slide.body; body.addEventListener("input", () => { slide.body = body.value; scheduleHistorySave() })
            card.append(label, heading, body); group.appendChild(card)
        }); root.appendChild(group)
        editorField(root, "Visual direction", pack.instagram.visual_direction, "instagram.visual_direction")
        editorField(root, "Alt text", pack.instagram.alt_text, "instagram.alt_text")
    } else if (state.platform === "x") {
        editorField(root, "Single post", pack.x.single, "x.single", false, 280, true)
        pack.x.thread.forEach((post, i) => editorField(root, `Thread · ${i + 1}/${pack.x.thread.length}`, post, `x.thread.${i}`, false, 280))
    } else editorField(root, "Threads post", pack.threads, "threads", true, 500, true)
}

function setPath(object, path, value) {
    const parts = path.split("."); const key = parts.pop(); const parent = parts.reduce((item, part) => item[part], object)
    parent[key] = path === "instagram.hashtags" ? value.split(/\s+/).filter(Boolean).slice(0, 5) : value
}

async function revise(instruction) {
    const variant = state.variants[state.activeVariant]; if (!variant || !instruction.trim()) return
    const buttons = $$('[data-revision], #custom-revision-button'); buttons.forEach(b => b.disabled = true)
    setStatus($("#output-status"), "Revising the full pack…")
    try {
        const data = await request("/clipwise/revise", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({
            pack:variant.pack, instruction, model:variant.generation.model_id, profile:profile(), angle:state.selectedAngle })})
        variant.pack = data.pack; variant.generation = data.generation; renderOutput(); saveCurrentPack(); setStatus($("#output-status"), "Revision ready.")
    } catch(error) { setStatus($("#output-status"), error.message, true) }
    finally { buttons.forEach(b => b.disabled = false) }
}

function markdown(pack) {
    return `# Social content pack\n\n## Instagram\n\n${pack.instagram.caption}\n\n${pack.instagram.hashtags.join(" ")}\n\n### Carousel\n\n${pack.instagram.carousel.map(s => `#### Slide ${s.slide}: ${s.heading}\n\n${s.body}`).join("\n\n")}\n\n### Visual direction\n\n${pack.instagram.visual_direction}\n\n### Alt text\n\n${pack.instagram.alt_text}\n\n## X\n\n### Single post\n\n${pack.x.single}\n\n### Thread\n\n${pack.x.thread.map((p,i)=>`${i+1}/${pack.x.thread.length} ${p}`).join("\n\n")}\n\n## Threads\n\n${pack.threads}\n`
}

async function copyText(text, button) {
    try { await navigator.clipboard.writeText(text); const old=button.textContent; button.textContent="Copied"; setTimeout(()=>button.textContent=old,1200) }
    catch (_) { setStatus($("#output-status"), "Clipboard access was blocked by the browser.", true) }
}

function renderHistory() {
    const root = $("#history-list"); root.innerHTML = ""; const items = history()
    if (!items.length) { root.textContent = "No saved packs yet."; return }
    items.forEach(item => { const card=document.createElement("div"); card.className="history-item"
        const title=document.createElement("strong"); title.textContent=item.angle?.title || item.source?.title || "Untitled pack"
        const meta=document.createElement("small"); meta.textContent=`${new Date(item.date).toLocaleString()} · ${item.generation.model_name || item.generation.model_id}`
        card.append(title,meta); card.addEventListener("click",()=>{state.selectedAngle=item.angle;state.transcript="";state.fromHistory=true;state.historyId=item.id;state.variants=[{pack:item.pack,generation:item.generation,preferred:true}];state.activeVariant=0;$("#output-section").classList.remove("hidden");renderOutput();toggleHistory(false);setStatus($("#output-status"),"Loaded from local history. Comparison needs the original source.")});root.appendChild(card) })
}

function toggleHistory(open) { $("#history-drawer").classList.toggle("open",open); $("#history-drawer").setAttribute("aria-hidden",String(!open)) }

$$('[data-stance]').forEach(button => button.addEventListener("click",()=>{state.stance=button.dataset.stance;$$('[data-stance]').forEach(x=>x.classList.toggle("active",x===button))}))
$$('[data-platform]').forEach(button => button.addEventListener("click",()=>{state.platform=button.dataset.platform;$$('[data-platform]').forEach(x=>x.classList.toggle("active",x===button));renderEditor()}))
$$('[data-revision]').forEach(button => button.addEventListener("click",()=>revise(button.dataset.revision)))
$("#source-input").addEventListener("input",e=>$("#source-count").textContent=`${e.target.value.length.toLocaleString()} characters`)
$$('#profile-bio,#profile-guidance,#profile-avoid,#profile-examples').forEach(field=>field.addEventListener("input",scheduleProfileSave))
$("#angle-button").addEventListener("click",findAngles)
$("#pack-button").addEventListener("click",()=>generatePack($("#model-select").value))
$("#compare-button").addEventListener("click",()=>generatePack($("#compare-model").value,true))
$("#custom-revision-button").addEventListener("click",()=>{revise($("#custom-revision").value);$("#custom-revision").value=""})
$("#copy-all").addEventListener("click",e=>copyText(markdown(state.variants[state.activeVariant].pack),e.currentTarget))
$("#export-markdown").addEventListener("click",()=>{const blob=new Blob([markdown(state.variants[state.activeVariant].pack)],{type:"text/markdown"});const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="podscribe-content-pack.md";a.click();URL.revokeObjectURL(a.href)})
$("#history-toggle").addEventListener("click",()=>toggleHistory(true));$("#history-close").addEventListener("click",()=>toggleHistory(false))
$("#clear-history").addEventListener("click",()=>{localStorage.removeItem(HISTORY_KEY);renderHistory()})

loadProfile(); renderHistory(); loadModels()
