const elements = {
    summariseButton: document.getElementById("summarise-btn"),
    stopButton: document.getElementById("stop-btn"),
    transcriptBox: document.getElementById("transcript"),
    styleBox: document.getElementById("style"),
    summaryText: document.getElementById("summary-text"),
    wordCount: document.getElementById("word-count"),
    historyList: document.getElementById("history-list"),
    clearHistoryButton: document.getElementById("clear-history-btn"),
    clipwise: document.getElementById("clipwise"),
    clipResults: document.getElementById("clip-results"),
    approachSlider: document.getElementById("approach-slider"),
    clipAllButton: document.getElementById("clip-all"),
    clipXButton: document.getElementById("clip-x"),
    clipThreadsButton: document.getElementById("clip-threads"),
    clipInstagramButton: document.getElementById("clip-instagram")
}

const HISTORY_KEY = "podscribe-history"
const HISTORY_LIMIT = 20
const APPROACH_MAP = [
    "quiet_learner",
    "curious_student",
    "builder_reflection",
    "conversation_starter",
    "braver_opinion"
]
const PLATFORM_NAMES = {
    x: "X (Twitter)",
    threads: "Threads",
    instagram: "Instagram"
}

function createApiAdapter() {
    async function postJson(url, body, signal) {
        const response = await fetch(url, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(body),
            signal: signal
        })

        const data = await response.json()
        if (!response.ok) {
            throw new Error(data.detail || data.error || "Server error: " + response.status)
        }

        return data
    }

    return {
        resolveTranscript(source, signal) {
            return postJson("/transcript", { source: source }, signal)
        },

        summarize(transcript, style, signal) {
            return postJson("/summarize", {
                transcript: transcript,
                style: style
            }, signal)
        },

        generateClips(transcript, platform, approach) {
            return postJson("/clipwise", {
                transcript: transcript,
                platform: platform,
                approach: approach
            })
        }
    }
}

function createHistoryStore(storage) {
    function list() {
        return JSON.parse(storage.getItem(HISTORY_KEY) || "[]")
    }

    function write(history) {
        storage.setItem(HISTORY_KEY, JSON.stringify(history))
    }

    return {
        list: list,

        add(summary, style, wordcount) {
            const history = list()
            history.unshift({
                summary: summary,
                style: style,
                wordcount: wordcount,
                date: new Date().toLocaleString()
            })

            write(history.slice(0, HISTORY_LIMIT))
        },

        clear() {
            storage.removeItem(HISTORY_KEY)
        }
    }
}

function createView(dom) {
    function renderMarkdown(target, markdown) {
        if (window.marked && window.marked.parse) {
            target.innerHTML = window.marked.parse(markdown)
            return
        }

        target.textContent = markdown
    }

    return {
        transcriptInput() {
            return dom.transcriptBox.value.trim()
        },

        selectedStyle() {
            return dom.styleBox.value
        },

        selectedApproach() {
            return APPROACH_MAP[Number(dom.approachSlider.value)] || "curious_student"
        },

        setBusy(isBusy) {
            dom.summariseButton.disabled = isBusy
            dom.summariseButton.textContent = isBusy ? "Summarising..." : "Summarise"
            dom.stopButton.disabled = !isBusy
        },

        setSummaryMessage(message) {
            dom.summaryText.textContent = message
        },

        clearWordCount() {
            dom.wordCount.textContent = ""
        },

        showSummary(summary, wordcount) {
            renderMarkdown(dom.summaryText, summary)
            dom.wordCount.textContent = "Word count: " + wordcount
        },

        showClipWise(isVisible) {
            dom.clipwise.style.display = isVisible ? "block" : "none"
        },

        clearClipResults() {
            dom.clipResults.innerHTML = ""
        },

        showClipLoading() {
            dom.clipResults.innerHTML = ""
            const message = document.createElement("p")
            message.textContent = "Generating clips..."
            dom.clipResults.appendChild(message)
        },

        showClipError(message) {
            dom.clipResults.innerHTML = ""
            const error = document.createElement("p")
            error.textContent = "Something went wrong: " + message
            dom.clipResults.appendChild(error)
        },

        showClips(clips, onCopy) {
            dom.clipResults.innerHTML = ""

            Object.entries(clips).forEach(function([key, content]) {
                const card = document.createElement("div")
                card.className = "clip-card"
                const post = typeof content === "string" ? content : content.post
                const imageIdea = typeof content === "string" ? "" : content.image_idea

                const heading = document.createElement("h3")
                heading.textContent = PLATFORM_NAMES[key] || key

                const body = document.createElement("p")
                body.textContent = post

                const copyPostButton = createCopyButton("Copy post", function(button) {
                    onCopy(post, button, "Copy post")
                })


                card.appendChild(heading)
                card.appendChild(body)
                card.appendChild(copyPostButton)

                if (imageIdea) {
                    const imageHeading = document.createElement("h4")
                    imageHeading.className = "clip-subheading"
                    imageHeading.textContent = "Image idea"

                    const imageBody = document.createElement("p")
                    imageBody.className = "image-idea"
                    imageBody.textContent = imageIdea

                    const copyImageButton = createCopyButton("Copy image idea", function(button) {
                        onCopy(imageIdea, button, "Copy image idea")
                    })

                    card.appendChild(imageHeading)
                    card.appendChild(imageBody)
                    card.appendChild(copyImageButton)
                }

                dom.clipResults.appendChild(card)
            })
        },

        showHistory(history, onSelect) {
            dom.historyList.innerHTML = ""

            if (history.length === 0) {
                const empty = document.createElement("li")
                empty.textContent = "No history yet."
                dom.historyList.appendChild(empty)
                return
            }

            history.forEach(function(item) {
                const li = document.createElement("li")
                const date = document.createElement("span")
                const preview = document.createElement("span")

                date.className = "history-date"
                date.textContent = item.date + " - " + item.style

                preview.className = "history-preview"
                preview.textContent = item.summary.substring(0, 100) + "..."

                li.appendChild(date)
                li.appendChild(preview)
                li.addEventListener("click", function() {
                    onSelect(item)
                })

                dom.historyList.appendChild(li)
            })
        }
    }
}

function createBrowserSession(api, view, historyStore) {
    const state = {
        controller: null,
        lastTranscript: null
    }

    function renderHistory() {
        view.showHistory(historyStore.list(), function(item) {
            view.showSummary(item.summary, item.wordcount)
        })
    }

    async function summarize() {
        const source = view.transcriptInput()
        const style = view.selectedStyle()

        if (!source) {
            view.setSummaryMessage("Please paste a transcript before summarising.")
            return
        }

        state.controller = new AbortController()
        view.setBusy(true)
        view.setSummaryMessage("Preparing transcript...")
        view.clearWordCount()

        try {
            const transcriptResult = await api.resolveTranscript(source, state.controller.signal)
            const transcript = transcriptResult.transcript

            view.setSummaryMessage("Summarising... please wait")
            const summaryResult = await api.summarize(
                transcript,
                style,
                state.controller.signal
            )

            view.showSummary(summaryResult.summary, summaryResult.word_count)
            historyStore.add(
                summaryResult.summary,
                summaryResult.style || style,
                summaryResult.word_count
            )
            renderHistory()

            state.lastTranscript = transcript
            view.showClipWise(true)
            view.clearClipResults()
        } catch (error) {
            if (error.name === "AbortError") {
                view.setSummaryMessage("Request cancelled.")
            } else {
                view.setSummaryMessage("Something went wrong: " + error.message)
            }
        } finally {
            view.setBusy(false)
            state.controller = null
        }
    }

    function stop() {
        if (state.controller) {
            state.controller.abort()
        }
    }

    async function generateClips(platform) {
        if (!state.lastTranscript) {
            return
        }

        view.showClipLoading()

        try {
            const clips = await api.generateClips(
                state.lastTranscript,
                platform,
                view.selectedApproach()
            )
            view.showClips(clips, copyClip)
        } catch (error) {
            view.showClipError(error.message)
        }
    }

    function copyClip(text, button, defaultLabel) {
        navigator.clipboard.writeText(text).then(function() {
            button.textContent = "Copied!"
            setTimeout(function() {
                button.textContent = defaultLabel
            }, 2000)
        }).catch(function() {
            button.textContent = "Copy failed"
            setTimeout(function() {
                button.textContent = defaultLabel
            }, 2000)
        })
    }

    function clearHistory() {
        historyStore.clear()
        renderHistory()
    }

    return {
        summarize: summarize,
        stop: stop,
        generateClips: generateClips,
        clearHistory: clearHistory,
        renderHistory: renderHistory
    }
}

const session = createBrowserSession(
    createApiAdapter(),
    createView(elements),
    createHistoryStore(localStorage)
)

elements.summariseButton.addEventListener("click", session.summarize)
elements.stopButton.addEventListener("click", session.stop)
elements.clearHistoryButton.addEventListener("click", session.clearHistory)
elements.clipAllButton.addEventListener("click", function() {
    session.generateClips("all")
})
elements.clipXButton.addEventListener("click", function() {
    session.generateClips("x")
})
elements.clipThreadsButton.addEventListener("click", function() {
    session.generateClips("threads")
})
elements.clipInstagramButton.addEventListener("click", function() {
    session.generateClips("instagram")
})

session.renderHistory()

function createCopyButton(label, onClick) {
    const button = document.createElement("button")
    button.className = "copy-btn"
    button.textContent = label
    button.addEventListener("click", function() {
        onClick(button)
    })
    return button
}
