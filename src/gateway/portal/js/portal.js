const { createApp, ref, onMounted, onUnmounted, watch, computed } = Vue;

const API_BASE = '/api';

const app = createApp({
    setup() {
        // --- 狀態變數 ---
        const currentPage = ref('warning'); 
        const macAddress = ref('');
        const originalUrl = ref('');
        
        const wheelRotation = ref(0);
        const isSpinning = ref(false);
        const spinResult = ref(null);

        const quiz = ref(null);
        const selectedAnswer = ref('');
        const quizResult = ref(null);
        const isLoadingQuiz = ref(false);
        const isSubmitting = ref(false);

        const isProcessingPayment = ref(false);
        const showFailModal = ref(false);
        const currentPenalty = ref(0);
        
        // 預設值是 9.99，但會被 localStorage 覆蓋
        const paymentAmount = ref(9.99);     
        const paymentReason = ref('');
        
        let statusCheckInterval = null;
        let paymentPollingInterval = null;

        const shortMac = computed(() => macAddress.value || 'Unknown Device');

        // --- 1. 初始化 ---
        onMounted(() => {
            const params = new URLSearchParams(window.location.search);
            macAddress.value = params.get('mac') || '00:00:00:00:00:00';
            originalUrl.value = params.get('original_url') || 'http://www.google.com';
            
            console.log(`System initialized for MAC: ${macAddress.value}`);

            // 1. 恢復金額 (如果有的話)
            const savedAmount = localStorage.getItem('payment_amount');
            if (savedAmount) {
                paymentAmount.value = parseInt(savedAmount);
            }

            // 2. 恢復頁面狀態
            const pendingFate = localStorage.getItem('user_fate');
            if (pendingFate) {
                currentPage.value = pendingFate;
            }

            statusCheckInterval = setInterval(checkAuthStatus, 3000);
        });

        const checkAuthStatus = async () => {
            if (!macAddress.value) return;
            try {
                const res = await fetch(`${API_BASE}/auth/status?mac=${macAddress.value}`);
                if (res.ok) {
                    const data = await res.json();
                    if (data.authorized) {
                        handleSuccessRedirect();
                    }
                }
            } catch (e) { /* ignore */ }
        };

        const handleSuccessRedirect = () => {
            if (statusCheckInterval) clearInterval(statusCheckInterval);
            if (paymentPollingInterval) clearInterval(paymentPollingInterval);

            // 清除所有暫存
            localStorage.removeItem('user_fate');
            localStorage.removeItem('payment_amount');
            
            currentPage.value = 'success';
            setTimeout(() => {
                window.location.href = 'https://www.google.com'; 
            }, 2000);
        };

        // --- 2. 監聽頁面切換 ---
        watch(currentPage, (val) => {
            if (val === 'quiz') {
                fetchQuiz();
            } else if (val === 'payment') {
                startPaymentPolling();
            }
        });

        // --- 3. 輪盤邏輯 ---
        const spinWheel = () => {
            if (isSpinning.value) return;
            isSpinning.value = true;
            spinResult.value = null;

            const totalSpin = 1800 + Math.floor(Math.random() * 360);
            wheelRotation.value += totalSpin;

            setTimeout(() => {
                isSpinning.value = false;
                const actualDegree = (360 - (wheelRotation.value % 360)) % 360;
                const sectionIndex = Math.floor(actualDegree / 60);

                if (sectionIndex % 2 === 0) {
                    spinResult.value = { type: 'quiz', text: '🧠 知識的贖罪' };
                    localStorage.setItem('user_fate', 'quiz');
                    setTimeout(() => { currentPage.value = 'quiz'; }, 1500);
                } else {
                    spinResult.value = { type: 'payment', text: '💰 資本的制裁' };
                    
                    // 設定並儲存金額
                    const amount = 100;
                    paymentAmount.value = amount;
                    localStorage.setItem('user_fate', 'payment');
                    localStorage.setItem('payment_amount', amount);
                    
                    paymentReason.value = '直接資本制裁';
                    setTimeout(() => { currentPage.value = 'payment'; }, 1500);
                }
            }, 4000);
        };

        // --- 4. 測驗邏輯 ---
        const fetchQuiz = async () => {
            isLoadingQuiz.value = true;
            quiz.value = null;
            selectedAnswer.value = '';
            quizResult.value = null;
            
            try {
                const res = await fetch(`${API_BASE}/quiz`);
                if (!res.ok) throw new Error('API Error');
                quiz.value = await res.json();
            } catch (e) {
                quiz.value = {
                    question: "系統暫時忙碌，請重新整理頁面。",
                    options: ["A", "B", "C", "D"],
                    id: "error"
                };
            } finally {
                isLoadingQuiz.value = false;
            }
        };

        const submitAnswer = async () => {
            isSubmitting.value = true;
            try {
                const res = await fetch(`${API_BASE}/quiz/answer`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        student_id: macAddress.value,
                        question_id: quiz.value.id,
                        answer: selectedAnswer.value
                    })
                });
                
                const result = await res.json();
                quizResult.value = result; 
                if (result.penalty !== undefined) currentPenalty.value = result.penalty;

                const isSuccess = result.correct || result.status === 'unlocked' || result.status === 'pay_penalty';

                if (isSuccess) {
                    if (result.status === 'pay_penalty') {
                        setTimeout(() => {
                            paymentAmount.value = result.penalty;
                            paymentReason.value = '恭喜答對！但需支付累積罰款';
                            
                            // 儲存金額
                            localStorage.setItem('user_fate', 'payment');
                            localStorage.setItem('payment_amount', result.penalty);
                            
                            currentPage.value = 'payment';
                        }, 2000);
                    } else {
                        setTimeout(() => handleSuccessRedirect(), 2000);
                    }
                } else {
                    if (result.wrong_count === 1) {
                        showFailModal.value = true; 
                    } else {
                        showFailModal.value = false;
                        setTimeout(() => {
                            quizResult.value = null; 
                            selectedAnswer.value = ''; 
                            fetchQuiz(); 
                        }, 2000);
                    }
                }
            } catch (e) {
                alert('提交失敗');
            } finally {
                isSubmitting.value = false;
            }
        };

        const retryQuiz = () => {
            showFailModal.value = false;
            selectedAnswer.value = '';
            quizResult.value = null;
            fetchQuiz();
        };

        const giveUpAndPay = async () => {
            showFailModal.value = false;
            try {
                const res = await fetch(`${API_BASE}/quiz/giveup`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ student_id: macAddress.value })
                });
                const data = await res.json();

                // 取得金額
                const finalAmount = data.amount;
                
                paymentAmount.value = finalAmount;
                localStorage.setItem('payment_amount', finalAmount);

                // 直接跳轉到 Telegram Bot 繳費
                // 格式：https://t.me/BOT_NAME?start=pay_金額
                window.location.href = `https://t.me/KDA_V2_bot?start=pay_${finalAmount}`;
                
                } catch(e) { 
                console.error("API Error, using fallback calculation");
                // 萬一網路或 API 錯誤的備案：直接用前端計算 (累積罰款 + 100)
                const fallbackAmount = currentPenalty.value + 100;
                window.location.href = `https://t.me/KDA_V2_bot?start=pay_${fallbackAmount}`;
            }
        };

        // --- 5. 付款 Polling ---
        const startPaymentPolling = () => {
            if (paymentPollingInterval) clearInterval(paymentPollingInterval);
            paymentPollingInterval = setInterval(async () => {
                try {
                    const res = await fetch(`${API_BASE}/payment/check?mac=${macAddress.value}`);
                    const data = await res.json();
                    if (data.status === 'paid') {
                        isProcessingPayment.value = true; 
                        handleSuccessRedirect();
                    }
                } catch (e) { console.error(e); }
            }, 3000);
        };

        const processPayment = async () => { /* 備用 */ };

        onUnmounted(() => {
            if (statusCheckInterval) clearInterval(statusCheckInterval);
            if (paymentPollingInterval) clearInterval(paymentPollingInterval);
        });

        window.resetTest = () => {
            localStorage.removeItem('user_fate');
            localStorage.removeItem('payment_amount');
            location.reload();
        };

        return {
            currentPage, shortMac,
            wheelRotation, isSpinning, spinResult,
            quiz, selectedAnswer, quizResult, isLoadingQuiz, isSubmitting,
            isProcessingPayment,
            showFailModal, currentPenalty, paymentAmount, paymentReason,
            spinWheel, submitAnswer, processPayment,
            retryQuiz, giveUpAndPay
        };
    }
});

app.mount('#app');
