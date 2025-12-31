// timer-widget.js
// Global Timer Registry to manage all timers
const timerRegistry = {
    allTimers: [],
    countdownTimers: [],
    byDriverId: {},
    lastGlobalTickTime: null,
    isTickRunning: false,

    registerTimer: function(timer) {
        this.allTimers.push(timer);

        // Register by type
        if (timer.countDirection === 'down') {
            this.countdownTimers.push(timer);
        }

        // Register by driver ID
        if (timer.targetId) {
            if (!this.byDriverId[timer.targetId]) {
                this.byDriverId[timer.targetId] = [];
            }
            this.byDriverId[timer.targetId].push(timer);
        }

        // Start the global tick if not already running
        if (!this.isTickRunning) {
            this.startGlobalTick();
        }
    },

    startGlobalTick: function() {
        this.isTickRunning = true;
        this.lastGlobalTickTime = Date.now();
        this.globalTick();
    },

    globalTick: function() {
        // Calculate time delta once
        const now = Date.now();
        const delta = (now - this.lastGlobalTickTime) / 1000;
        this.lastGlobalTickTime = now;

        // Update all active timers with the same delta
        this.allTimers.forEach(timer => {
            if (!timer.paused && timer.isactive) {
                timer.update(delta);
            }
        });

        // Continue the global tick
        requestAnimationFrame(() => this.globalTick());
    }
};

class TimerWidget {
    constructor(options) {
        this.element = document.getElementById(options.elementId);
        this.startValue = options.startValue || 0; // In seconds
        this.countDirection = options.countDirection || 'up'; // 'up' or 'down'
        this.paused = options.initialPaused || false;
        this.targetId = options.targetId; // Store driver ID for session updates
        this.precision = options.precision || 0; // Decimal places
        this.currentValue = this.startValue;
        this.timerType = options.timerType || 'countdownDisplay'; // 'totaltime', 'sessiontime', 'countdownDisplay'
        this.limit = options.limit || null; // Optional limit value in seconds
        if (this.timerType == 'countdownDisplay') {
            this.isactive = true;
        } else {
            this.isactive = !this.paused;
        }

        // Format options
        this.showHours = options.showHours !== undefined ? options.showHours : true;
        this.showMinutes = options.showMinutes !== undefined ? options.showMinutes : true;
        this.showSeconds = true;

        // Initial render
        this.render();

        // Register with the global registry
        timerRegistry.registerTimer(this);
    }

    // New method - update currentValue based on delta time
    update(delta) {
        if (this.countDirection === 'up') {
            this.currentValue += delta;
        } else {
            this.currentValue -= delta;
            // Don't go below zero for countdown timers
            if (this.currentValue < 0) {
                this.currentValue = 0;
                this.pause();
            }
        }
        this.render();
    }

    start() {
        if (this.isactive) {
            this.paused = false;
        }
    }

    pause() {
        this.paused = true;
    }

    resume() {
        if (this.isactive) {
            this.paused = false;
        }
    }

    activate() {
        if (this.targetId) {
            this.isactive = true;
            this.paused = false;
            this.render(); // Re-render to update colors
        }
    }

    deactivate() {
        if (this.targetId) {
            this.isactive = false;
            this.paused = true;
            this.render(); // Re-render to update colors
        }
    }

    reset(newStartValue) {
        this.currentValue = newStartValue !== undefined ? newStartValue : this.startValue;
        this.render();
    }

    formatTime(totalSeconds) {
        const totalSecondsAbs = Math.abs(totalSeconds);
        const hours = Math.floor(totalSecondsAbs / 3600);
        const remainingAfterHours = totalSecondsAbs % 3600;
        const minutes = Math.floor(remainingAfterHours / 60);
        const seconds = remainingAfterHours % 60;

        let formattedTime = '';

        if (this.showHours) {
            formattedTime += String(hours).padStart(2, '0') + ':';
        }

        if (this.showMinutes) {
            formattedTime += String(minutes).padStart(2, '0') + ':';
        }

        if (this.precision > 0) {
            formattedTime += seconds.toFixed(this.precision).padStart(3 + this.precision, '0');
        } else {
            formattedTime += String(Math.floor(seconds)).padStart(2, '0');
        }

        return totalSeconds < 0 ? '-' + formattedTime : formattedTime;
    }

    render() {
        if (this.element) {
            this.element.textContent = this.formatTime(this.currentValue);

            // Reset all classes first
            this.element.classList.remove('timer-ended', 'timer-paused', 'timer-frozen', 'timer-over', 'timer-active');

            // Add active class for active drivers (black color)
            if (this.isactive && !this.paused) {
                this.element.classList.add('timer-active');
            }

            // Add classes for styling
            if (this.currentValue <= 0 && this.countDirection === 'down') {
                this.element.classList.add('timer-ended');
            }

            // Handle paused state styling
            if (this.paused) {
                if (this.countDirection === 'down') {
                    // Countdown timers get timer-paused
                    this.element.classList.add('timer-paused');
                } else {
                    // Count-up timers get timer-frozen
                    this.element.classList.add('timer-frozen');
                }
            }

            // Add timer-over class if limit is set and exceeded
            let isOverLimit = false;
            if (this.limit !== null) {
                if ((this.countDirection === 'up' && this.currentValue > this.limit) ||
                    (this.countDirection === 'down' && this.currentValue < this.limit)) {
                    this.element.classList.add('timer-over');
                    isOverLimit = true;
                }
            }

            // Update LED indicator if this timer has a driver ID
            this.updateLEDIndicator(isOverLimit);
        }
    }

    updateLEDIndicator(isOverLimit) {
        // Only update LED for driver-specific timers that have a limit set
        if (!this.targetId || this.timerType === 'countdownDisplay' || this.limit === null) {
            return;
        }

        // Find the driver row for this timer
        const driverRow = document.querySelector(`tr[data-driver-id="${this.targetId}"]`);
        if (!driverRow) {
            return;
        }

        // Find the first cell (driver name cell) in the row
        const nameCell = driverRow.querySelector('td:first-child');
        if (!nameCell) {
            return;
        }

        // Check if LED already exists
        let led = nameCell.querySelector('.driver-limit-led');

        if (isOverLimit) {
            // Show LED if over limit
            if (!led) {
                // Create LED if it doesn't exist
                led = document.createElement('span');
                led.className = 'driver-limit-led';
                led.title = 'Driver exceeded time limit';
                nameCell.insertBefore(led, nameCell.firstChild);
            }
        } else {
            // Hide/remove LED if not over limit
            if (led) {
                led.remove();
            }
        }
    }

    updatePauseState(isPaused) {
        if (isPaused) {
            this.pause();
        } else {
            this.resume();
        }
    }

    updateRemainingTime(seconds) {
        if (this.countDirection === 'down') {
            this.currentValue = seconds;
            this.render();
        }
    }

    handleSessionUpdate(status, tspent) {
        if (this.timerType === 'sessiontime') {
            if (status === "start") {
                this.reset(0);
                this.activate();
                this.start();
                if (this.element) {
                    this.element.style.visibility = 'visible';
                }
            } else if (status === "end") {
                this.deactivate();
                if (this.element) {
                    this.element.style.visibility = 'hidden';
                }
            } else if (status === "register") {
                if (this.element) {
                    this.element.style.visibility = 'visible';
                }
                this.reset(0)
            } else { //reset
                this.deactivate();
                this.reset(0)
                if (this.element) {
                    this.element.style.visibility = 'hidden';
                }
            }
        } else if (this.timerType === 'totaltime') {
            if (status === "start") {
                this.activate();
                this.reset(tspent);
                this.start();
            } else if (status === "end") {
                this.deactivate();
            } else if (status === "reset") {
                this.deactivate();
                this.reset(0)
            } else if (status === "register") {
                this.reset(tspent)
            }
        }
    }
}

// This function creates all timer widgets on a page and registers them with their driver IDs
function initializeTimers() {
    // Find all timer placeholders
    const timerPlaceholders = document.querySelectorAll('[data-timer]');

    timerPlaceholders.forEach(placeholder => {
        const config = JSON.parse(placeholder.getAttribute('data-config'));

        // Create the timer
        new TimerWidget({
            elementId: placeholder.id,
            startValue: config.startValue || 0,
            countDirection: config.countDirection || 'up',
            initialPaused: config.initialPaused || false,
            targetId: config.targetId,
            timerType: config.timerType,
            showHours: config.showHours,
            showMinutes: config.showMinutes,
            limit: config.limit || null
        });
    });
}

// Initialize all timers when the DOM is ready
document.addEventListener('DOMContentLoaded', initializeTimers);

// Listen for custom event to refresh a specific team's timers
document.addEventListener('refreshTeamTimers', function(e) {
    if (e.detail && e.detail.teamId) {
        const teamContainer = document.querySelector(`#team-slide-${e.detail.teamId}`);
        if (teamContainer) {
            // Find all timer placeholders in this team's container
            const timerPlaceholders = teamContainer.querySelectorAll('[data-timer]');

            timerPlaceholders.forEach(placeholder => {
                const config = JSON.parse(placeholder.getAttribute('data-config'));

                // Create the timer
                new TimerWidget({
                    elementId: placeholder.id,
                    startValue: config.startValue || 0,
                    countDirection: config.countDirection || 'up',
                    initialPaused: config.initialPaused || false,
                    targetId: config.targetId,
                    timerType: config.timerType,
                    showHours: config.showHours,
                    showMinutes: config.showMinutes,
                    limit: config.limit || null
                });
            });
        }
    }
});
