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
});

// Exam logic
if (document.querySelector('.exam-container')) {
    let currentIndex = 0;
    let answers = {};
    let timerInterval;
    let stream = null;
    const isPro = typeof isPro !== 'undefined' ? isPro : false;

    function renderQuestion() {
        const q = questions[currentIndex];
        const questionArea = document.getElementById('question-area');
        questionArea.innerHTML = `
            <div class="question-text">${q.serial_no}. ${q.question}</div>
            <div class="options">
                <label class="option"><input type="radio" name="answer" value="${q.option1}" ${answers[q.id] === q.option1 ? 'checked' : ''}> A. ${q.option1}</label>
                <label class="option"><input type="radio" name="answer" value="${q.option2}" ${answers[q.id] === q.option2 ? 'checked' : ''}> B. ${q.option2}</label>
                <label class="option"><input type="radio" name="answer" value="${q.option3}" ${answers[q.id] === q.option3 ? 'checked' : ''}> C. ${q.option3}</label>
                <label class="option"><input type="radio" name="answer" value="${q.option4}" ${answers[q.id] === q.option4 ? 'checked' : ''}> D. ${q.option4}</label>
            </div>
        `;
        document.querySelectorAll('input[name="answer"]').forEach(radio => {
            radio.addEventListener('change', (e) => {
                answers[q.id] = e.target.value;
                updateProgress();
            });
        });
        document.getElementById('prev-btn').disabled = currentIndex === 0;
        document.getElementById('next-btn').style.display = currentIndex === questions.length - 1 ? 'none' : 'inline-block';
        document.getElementById('submit-btn').style.display = currentIndex === questions.length - 1 ? 'inline-block' : 'none';
    }

    function updateProgress() {
        const answered = Object.keys(answers).length;
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

    async function submitExam() {
        clearInterval(timerInterval);
        if (stream) {
            stream.getTracks().forEach(track => track.stop());
        }
        const response = await fetch('/submit-exam', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ exam_code: examCode, answers: answers })
        });
        const data = await response.json();
        document.getElementById('final-score').textContent = data.score;
        document.getElementById('total-possible').textContent = data.total;
        document.getElementById('result-modal').style.display = 'flex';
        if (document.exitFullscreen) document.exitFullscreen();
    }

    function initFullscreen() {
        document.documentElement.requestFullscreen();
        document.addEventListener('fullscreenchange', () => {
            if (!document.fullscreenElement && !document.webkitFullscreenElement) {
                submitExam();
            }
        });
    }

    async function initProctoring() {
        if (!isPro) return;
        initFullscreen();
        try {
            stream = await navigator.mediaDevices.getUserMedia({ video: true });
            const video = document.createElement('video');
            video.srcObject = stream;
            video.play();
            const canvas = document.createElement('canvas');
            const context = canvas.getContext('2d');
            let lastFrame = null;
            setInterval(() => {
                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
                context.drawImage(video, 0, 0, canvas.width, canvas.height);
                const currentFrame = canvas.toDataURL();
                if (lastFrame && currentFrame !== lastFrame) {
                    fetch('/proctor-violation', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ exam_code: examCode, violation: 'motion_detected', image: currentFrame })
                    });
                }
                lastFrame = currentFrame;
            }, 5000);
        } catch (err) {
            console.log('Camera access denied');
        }
    }

    document.getElementById('prev-btn').addEventListener('click', () => {
        if (currentIndex > 0) {
            currentIndex--;
            renderQuestion();
        }
    });
    document.getElementById('next-btn').addEventListener('click', () => {
        if (currentIndex < questions.length - 1) {
            currentIndex++;
            renderQuestion();
        }
    });
    document.getElementById('submit-btn').addEventListener('click', submitExam);
    renderQuestion();
    startTimer(timerMinutes);
    initProctoring();
}

function downloadStudentResponses(examCode) {
    const studentId = prompt('Enter Student ID:');
    if(studentId) {
        window.open(`/download-student-responses/${examCode}/${studentId}`, '_blank');
    }
}