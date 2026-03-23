// static/script.js
document.addEventListener('DOMContentLoaded', function() {
    // Theme toggle
    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
        themeToggle.addEventListener('click', () => {
            document.body.classList.toggle('dark-theme');
            const isDark = document.body.classList.contains('dark-theme');
            localStorage.setItem('theme', isDark ? 'dark' : 'light');
            themeToggle.textContent = isDark ? '☀️' : '🌙';
        });
        const savedTheme = localStorage.getItem('theme');
        if (savedTheme === 'dark') {
            document.body.classList.add('dark-theme');
            themeToggle.textContent = '☀️';
        }
    }

    // Login tabs
    const tabBtns = document.querySelectorAll('.tab-btn');
    const forms = document.querySelectorAll('.login-form');
    if (tabBtns.length) {
        tabBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                tabBtns.forEach(b => b.classList.remove('active'));
                forms.forEach(f => f.classList.remove('active'));
                btn.classList.add('active');
                document.getElementById(`${btn.dataset.tab}-login-form`).classList.add('active');
            });
        });
    }

    // Modal handlers
    window.showModal = function(id) {
        document.getElementById(id).style.display = 'flex';
    };
    window.closeModal = function(id) {
        document.getElementById(id).style.display = 'none';
    };
    window.closeModalAndRedirect = function() {
        window.location.href = '/student-dashboard';
    };
    
    // Auto-hide alerts
    setTimeout(() => {
        document.querySelectorAll('.alert').forEach(alert => {
            alert.style.opacity = '0';
            setTimeout(() => alert.remove(), 300);
        });
    }, 5000);
    
    // Close modal on outside click
    window.onclick = function(event) {
        if (event.target.classList.contains('modal')) {
            event.target.style.display = 'none';
        }
    };
});

// Exam logic
if (document.querySelector('.exam-container')) {
    let currentIndex = 0;
    let answers = {};
    let theoryAnswers = {};
    let timerInterval;
    let stream = null;
    let motionInterval = null;
    let violationCount = 0;
    let fullscreenExitCount = 0;
    let examStarted = false;
    let lastFrame = null;
    let proctoringActive = false;
    const isPro = typeof isPro !== 'undefined' ? isPro : false;
    const VIOLATION_LIMIT = 7; // Updated to 7 violations before auto-submit

    function renderQuestion() {
        const q = questions[currentIndex];
        const questionArea = document.getElementById('question-area');
        const isTheory = examType === 'theory' || (!q.option1 && !q.option2 && !q.option3 && !q.option4);
        
        if (isTheory) {
            questionArea.innerHTML = `
                <div class="question-text">${escapeHtml(q.serial_no)}. ${escapeHtml(q.question)}</div>
                <div class="theory-question">
                    <textarea id="theory-answer" rows="6" placeholder="Type your answer here...">${theoryAnswers[q.id] || ''}</textarea>
                    <div id="word-count" style="font-size:0.75rem;color:var(--text-muted);margin-top:0.5rem;">Words: ${(theoryAnswers[q.id] || '').split(/\s+/).filter(w=>w.length).length}</div>
                </div>
            `;
            const textarea = document.getElementById('theory-answer');
            if (textarea) {
                textarea.addEventListener('input', (e) => {
                    theoryAnswers[q.id] = e.target.value;
                    updateProgress();
                    const wordCount = e.target.value.split(/\s+/).filter(w => w.length).length;
                    document.getElementById('word-count').textContent = `Words: ${wordCount}`;
                });
            }
        } else {
            questionArea.innerHTML = `
                <div class="question-text">${escapeHtml(q.serial_no)}. ${escapeHtml(q.question)}</div>
                <div class="options">
                    <label class="option"><input type="radio" name="answer" value="${escapeHtml(q.option1)}" ${answers[q.id] === q.option1 ? 'checked' : ''}> A. ${escapeHtml(q.option1)}</label>
                    <label class="option"><input type="radio" name="answer" value="${escapeHtml(q.option2)}" ${answers[q.id] === q.option2 ? 'checked' : ''}> B. ${escapeHtml(q.option2)}</label>
                    <label class="option"><input type="radio" name="answer" value="${escapeHtml(q.option3)}" ${answers[q.id] === q.option3 ? 'checked' : ''}> C. ${escapeHtml(q.option3)}</label>
                    <label class="option"><input type="radio" name="answer" value="${escapeHtml(q.option4)}" ${answers[q.id] === q.option4 ? 'checked' : ''}> D. ${escapeHtml(q.option4)}</label>
                </div>
            `;
            document.querySelectorAll('input[name="answer"]').forEach(radio => {
                radio.addEventListener('change', (e) => {
                    answers[q.id] = e.target.value;
                    updateProgress();
                });
            });
        }
        
        document.getElementById('prev-btn').disabled = currentIndex === 0;
        document.getElementById('next-btn').style.display = currentIndex === questions.length - 1 ? 'none' : 'inline-block';
        document.getElementById('submit-btn').style.display = currentIndex === questions.length - 1 ? 'inline-block' : 'none';
    }

    function updateProgress() {
        const answered = Object.keys(answers).length + Object.keys(theoryAnswers).length;
        document.getElementById('answered-count').textContent = answered;
        const progressPercent = (answered / questions.length) * 100;
        document.getElementById('progress').style.width = `${progressPercent}%`;
    }

    function startTimer(minutes) {
        let time = minutes * 60;
        const timerElement = document.getElementById('timer');
        timerInterval = setInterval(() => {
            const mins = Math.floor(time / 60);
            const secs = time % 60;
            timerElement.textContent = `${mins.toString().padStart(2,'0')}:${secs.toString().padStart(2,'0')}`;
            if (time <= 0) {
                clearInterval(timerInterval);
                submitExam();
            }
            time--;
        }, 1000);
    }

    function escapeHtml(text) {
        if (!text) return '';
        return String(text).replace(/[&<>]/g, function(m) {
            return m === '&' ? '&amp;' : (m === '<' ? '&lt;' : '&gt;');
        });
    }

    function enterFullscreen() {
        const elem = document.documentElement;
        if (elem.requestFullscreen) elem.requestFullscreen();
        else if (elem.webkitRequestFullscreen) elem.webkitRequestFullscreen();
        else if (elem.msRequestFullscreen) elem.msRequestFullscreen();
    }

    function isFullscreen() {
        return document.fullscreenElement || document.webkitFullscreenElement;
    }

    async function addViolation(type) {
        if (!proctoringActive) return;
        
        violationCount++;
        const violationCounter = document.getElementById('violation-count');
        if (violationCounter) violationCounter.textContent = violationCount;
        
        let img = null;
        if (stream && stream.getVideoTracks().length > 0) {
            const video = document.getElementById('camera-video');
            if (video && video.videoWidth > 0) {
                const canvas = document.createElement('canvas');
                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
                canvas.getContext('2d').drawImage(video, 0, 0);
                img = canvas.toDataURL('image/jpeg', 0.5);
            }
        }
        
        await fetch('/proctor-violation', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ exam_code: examCode, violation: type, image: img })
        });
        
        showViolationWarning(`⚠️ Violation detected: ${type} (${violationCount}/${VIOLATION_LIMIT})`);
        
        if (violationCount >= VIOLATION_LIMIT) {
            showViolationWarning('⚠️ Maximum violations reached! Auto-submitting exam...');
            setTimeout(() => submitExam(), 2000);
        }
    }

    function showViolationWarning(msg) {
        const warning = document.createElement('div');
        warning.className = 'violation-warning';
        warning.innerHTML = msg;
        document.body.appendChild(warning);
        setTimeout(() => warning.remove(), 3000);
    }

    async function initCamera() {
        if (!isPro) return;
        try {
            stream = await navigator.mediaDevices.getUserMedia({ 
                video: { width: 640, height: 480, facingMode: 'user' }, 
                audio: false 
            });
            const video = document.getElementById('camera-video');
            if (video) video.srcObject = stream;
            startMotionDetection();
            // Camera permission granted - not a violation
        } catch (err) {
            console.log('Camera access denied');
            // Camera permission denied - not a violation
        }
    }

    function startMotionDetection() {
        const video = document.getElementById('camera-video');
        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d');
        
        motionInterval = setInterval(() => {
            if (video && video.videoWidth > 0) {
                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
                ctx.drawImage(video, 0, 0);
                const currentFrame = ctx.getImageData(0, 0, canvas.width, canvas.height);
                
                if (lastFrame) {
                    let changed = 0;
                    let total = 0;
                    for (let i = 0; i < currentFrame.data.length; i += 200) {
                        const diff = Math.abs(currentFrame.data[i] - lastFrame.data[i]) +
                                    Math.abs(currentFrame.data[i+1] - lastFrame.data[i+1]) +
                                    Math.abs(currentFrame.data[i+2] - lastFrame.data[i+2]);
                        if (diff > 80) changed++;
                        total++;
                    }
                    if (changed / total > 0.3 && proctoringActive) {
                        addViolation('excessive_movement');
                    }
                }
                lastFrame = currentFrame;
            }
        }, 3000);
    }

    function stopProctoring() {
        proctoringActive = false;
        if (motionInterval) {
            clearInterval(motionInterval);
            motionInterval = null;
        }
        if (stream) {
            stream.getTracks().forEach(track => track.stop());
            stream = null;
        }
    }

    async function submitExam() {
        clearInterval(timerInterval);
        stopProctoring();
        
        const submitBtn = document.getElementById('submit-btn');
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.textContent = 'Submitting...';
        }
        
        try {
            const response = await fetch('/submit-exam', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    exam_code: examCode, 
                    answers: answers, 
                    theory_answers: theoryAnswers,
                    attempt_id: attemptId 
                })
            });
            const data = await response.json();
            
            document.getElementById('final-score').textContent = data.score;
            document.getElementById('total-possible').textContent = data.total;
            const percentage = (data.score / data.total * 100).toFixed(1);
            document.getElementById('score-percentage').innerHTML = `<strong>${percentage}%</strong>`;
            document.getElementById('result-modal').style.display = 'flex';
            
            if (document.exitFullscreen) document.exitFullscreen();
        } catch (error) {
            alert('Error submitting exam. Please try again.');
        }
    }

    function startExam() {
        if (examStarted) return;
        examStarted = true;
        proctoringActive = true;
        
        const fullscreenPrompt = document.getElementById('fullscreen-prompt');
        const examContainer = document.querySelector('.exam-container');
        const cameraContainer = document.getElementById('camera-container');
        const violationCounter = document.getElementById('violation-counter');
        
        if (fullscreenPrompt) fullscreenPrompt.style.display = 'none';
        if (examContainer) examContainer.style.display = 'block';
        
        renderQuestion();
        startTimer(timerMinutes);
        
        if (isPro) {
            initCamera();
            if (cameraContainer) cameraContainer.style.display = 'block';
            if (violationCounter) violationCounter.style.display = 'block';
        }
        
        // Set up fullscreen change monitoring
        document.addEventListener('fullscreenchange', handleFullscreenChange);
        document.addEventListener('webkitfullscreenchange', handleFullscreenChange);
    }
    
    let fullscreenEntryLogged = false;
    
    function handleFullscreenChange() {
        if (!examStarted) return;
        
        if (!isFullscreen()) {
            fullscreenExitCount++;
            if (fullscreenExitCount > 0 && proctoringActive) {
                addViolation('fullscreen_exit');
                showViolationWarning('⚠️ Please stay in fullscreen mode!');
                if (fullscreenExitCount >= 1) {
                    showViolationWarning('⚠️ You exited fullscreen! Exam will be submitted.');
                    setTimeout(() => submitExam(), 3000);
                }
            }
        } else if (!fullscreenEntryLogged) {
            fullscreenEntryLogged = true;
            // Fullscreen entry - not a violation
        }
    }

    // Force fullscreen when starting exam (without user interaction needed)
    function forceFullscreen() {
        enterFullscreen();
        setTimeout(() => {
            if (isFullscreen()) {
                startExam();
            } else {
                // Try again
                enterFullscreen();
                setTimeout(() => {
                    if (isFullscreen()) {
                        startExam();
                    } else {
                        // Fallback: start anyway but warn
                        startExam();
                        showViolationWarning('⚠️ Please press F11 for fullscreen mode');
                    }
                }, 500);
            }
        }, 500);
    }

    // Anti-cheat measures (no right-click violation)
    function setupAntiCheat() {
        document.addEventListener('visibilitychange', () => {
            if (examStarted && proctoringActive && document.hidden) {
                addViolation('tab_switch');
            }
        });
        
        document.addEventListener('keydown', (e) => {
            if (!examStarted || !proctoringActive) return;
            
            if (e.key === 'F11') {
                e.preventDefault();
                return false;
            }
            
            const forbiddenKeys = ['c', 'v', 'x', 'p', 's', 'F12', 'I', 'Tab'];
            if ((e.ctrlKey && forbiddenKeys.includes(e.key)) || 
                (e.ctrlKey && e.shiftKey && e.key === 'I') ||
                (e.ctrlKey && e.key === 'Tab') ||
                (e.altKey && e.key === 'Tab') ||
                e.key === 'F12') {
                e.preventDefault();
                addViolation('keyboard_shortcut');
                return false;
            }
        });
        
        // Right-click is NOT recorded as violation
        document.addEventListener('contextmenu', (e) => {
            if (examStarted && proctoringActive) {
                e.preventDefault();
                // Do NOT record as violation - just prevent
                return false;
            }
        });
        
        document.addEventListener('copy', (e) => {
            if (examStarted && proctoringActive) {
                e.preventDefault();
                addViolation('copy_attempt');
                return false;
            }
        });
        
        document.addEventListener('paste', (e) => {
            if (examStarted && proctoringActive) {
                e.preventDefault();
                addViolation('paste_attempt');
                return false;
            }
        });
        
        window.addEventListener('blur', () => {
            if (examStarted && proctoringActive) addViolation('window_blur');
        });
    }

    // Event listeners
    const prevBtn = document.getElementById('prev-btn');
    const nextBtn = document.getElementById('next-btn');
    const submitBtn = document.getElementById('submit-btn');
    
    if (prevBtn) {
        prevBtn.addEventListener('click', () => {
            if (currentIndex > 0) {
                currentIndex--;
                renderQuestion();
            }
        });
    }
    
    if (nextBtn) {
        nextBtn.addEventListener('click', () => {
            if (currentIndex < questions.length - 1) {
                currentIndex++;
                renderQuestion();
            }
        });
    }
    
    if (submitBtn) {
        submitBtn.addEventListener('click', () => {
            if (confirm('Are you sure you want to submit your exam?')) {
                submitExam();
            }
        });
    }
    
    const enterFullscreenBtn = document.getElementById('enter-fullscreen-btn');
    if (enterFullscreenBtn) {
        enterFullscreenBtn.addEventListener('click', forceFullscreen);
    }
    
    // Start the exam process
    setupAntiCheat();
    forceFullscreen();
    
    // Auto-save progress
    setInterval(() => {
        if (examStarted && (Object.keys(answers).length || Object.keys(theoryAnswers).length)) {
            localStorage.setItem(`exam_${examCode}_progress`, JSON.stringify({
                answers,
                theoryAnswers,
                timestamp: new Date()
            }));
        }
    }, 30000);
    
    window.addEventListener('beforeunload', (e) => {
        if (examStarted && Object.keys(answers).length + Object.keys(theoryAnswers).length < questions.length) {
            e.preventDefault();
            e.returnValue = 'You have not completed the exam. Are you sure you want to leave?';
        }
    });
}

<script>
    document.addEventListener('DOMContentLoaded', function() {
        const themeToggle = document.getElementById('theme-toggle');
        if (themeToggle) {
            const savedTheme = localStorage.getItem('theme');
            if (savedTheme === 'dark') {
                document.body.classList.add('dark-theme');
                themeToggle.textContent = '☀️';
            }
            themeToggle.addEventListener('click', function() {
                document.body.classList.toggle('dark-theme');
                const isDark = document.body.classList.contains('dark-theme');
                localStorage.setItem('theme', isDark ? 'dark' : 'light');
                themeToggle.textContent = isDark ? '☀️' : '🌙';
            });
        }
    });
</script>