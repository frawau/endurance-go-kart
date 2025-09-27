/**
 * Weight Penalty Widget Library
 * Reusable JavaScript component for managing weight-penalty configurations
 */

class WeightPenaltyWidget {
    constructor(containerId, operatorId, pairsContainerId, addButtonId, hiddenInputId) {
        this.container = document.getElementById(containerId);
        this.operatorSelect = document.getElementById(operatorId);
        this.pairsContainer = document.getElementById(pairsContainerId);
        this.addButton = document.getElementById(addButtonId);
        this.hiddenInput = document.getElementById(hiddenInputId);
        
        if (!this.container || !this.operatorSelect || !this.pairsContainer || !this.addButton || !this.hiddenInput) {
            console.error('WeightPenaltyWidget: Required elements not found');
            return;
        }
        
        this.init();
    }
    
    init() {
        // Set the initial JSON value
        this.weightPenaltyData = JSON.parse(this.hiddenInput.value || '[]');

        // Add event listeners
        this.addButton.addEventListener('click', () => {
            this.addWeightPair();
            this.updateHiddenField();
        });

        // Update hidden field when any value changes
        this.container.addEventListener('change', (e) => {
            this.updateHiddenField();

            if (
                e.target === this.operatorSelect ||
                e.target.classList.contains('weight-value') ||
                e.target.classList.contains('penalty-value')
            ) {
                const pairs = this.collectPairs();
                if (this.shouldRenderSorted(pairs)) {
                    this.renderSortedPairs();
                }
            }
        });

        this.operatorSelect.addEventListener('change', () => this.updateOperatorDisplay());

        // Initialize from existing data
        this.initializeFromData();
    }
    
    shouldRenderSorted(pairs) {
        if (!pairs.length) return false;

        let hasPositive = false;

        for (const [weight, penalty] of pairs) {
            if (
                weight === '' || penalty === '' ||
                isNaN(weight) || isNaN(penalty)
            ) {
                return false; // missing or invalid values
            }

            if (parseFloat(weight) > 0 || parseFloat(penalty) > 0) {
                hasPositive = true;
            } else {
                hasPositive = false;
            }
        }

        return hasPositive;
    }

    collectPairs() {
        const pairs = [];
        this.pairsContainer.querySelectorAll('.weight-pair-row').forEach(row => {
            const weightValue = row.querySelector('.weight-value')?.value;
            const penaltyValue = row.querySelector('.penalty-value')?.value;
            pairs.push([parseFloat(weightValue), parseFloat(penaltyValue)]);
        });
        return pairs;
    }

    addWeightPair(weight = '', penalty = '') {
        const row = document.createElement('div');
        row.className = 'weight-pair-row d-flex mb-2 align-items-center';

        row.innerHTML = `
            <div class="operator-display mx-2">${this.operatorSelect.value}</div>
            <input type="number" step="0.5" class="form-control weight-value mr-2" value="${weight}" placeholder="Weight">
            <div class="operator-display mx-2"><i class="fa-solid fa-arrow-right"></i></div>
            <input type="number" step="0.5" class="form-control penalty-value ml-2" value="${penalty}" placeholder="Penalty">
            <button type="button" class="btn btn-danger btn-sm ml-2 remove-pair">
                <i class="fa-solid fa-trash fa-lg"></i>
            </button>
        `;

        row.querySelector('.remove-pair').addEventListener('click', () => {
            row.remove();
            this.updateHiddenField();
        });

        this.pairsContainer.appendChild(row);
    }

    updateOperatorDisplay() {
        const operatorValue = this.operatorSelect.value;
        document.querySelectorAll('.operator-display').forEach(element => {
            if (!element.querySelector('i')) { // Skip arrow icons
                element.textContent = operatorValue;
            }
        });
    }

    updateHiddenField() {
        const operator = this.operatorSelect.value;
        const pairs = this.collectPairs();

        // Sort pairs based on operator
        this.sortPairsByOperator(pairs, operator);

        // Create the JSON structure
        const weightPenaltyData = [operator, ...pairs];
        this.hiddenInput.value = JSON.stringify(weightPenaltyData);
    }

    sortPairsByOperator(pairs, operator) {
        if ([">=", ">"].includes(operator)) {
            // Sort pairs by weight in descending order
            pairs.sort((a, b) => b[0] - a[0]);
        } else {
            // Sort pairs by weight in ascending order
            pairs.sort((a, b) => a[0] - b[0]);
        }
        return pairs;
    }

    renderSortedPairs() {
        // Save current pairs
        const pairs = this.collectPairs();
        const operator = this.operatorSelect.value;

        // Sort them
        this.sortPairsByOperator(pairs, operator);

        // Clear container
        this.pairsContainer.innerHTML = '';

        // Re-render in sorted order
        pairs.forEach(pair => {
            this.addWeightPair(pair[0], pair[1]);
        });
    }

    initializeFromData() {
        // Clear existing pairs
        this.pairsContainer.innerHTML = '';

        if (Array.isArray(this.weightPenaltyData) && this.weightPenaltyData.length > 0) {
            // Set the operator
            if (typeof this.weightPenaltyData[0] === 'string') {
                this.operatorSelect.value = this.weightPenaltyData[0];
            }
            this.updateOperatorDisplay();

            // Add pairs from the data
            for (let i = 1; i < this.weightPenaltyData.length; i++) {
                if (Array.isArray(this.weightPenaltyData[i]) && this.weightPenaltyData[i].length === 2) {
                    this.addWeightPair(this.weightPenaltyData[i][0], this.weightPenaltyData[i][1]);
                }
            }
        } else {
            // Add one empty pair if no data
            this.addWeightPair();
        }

        // Update the hidden input with the initialized data and sort the UI
        this.updateHiddenField();
    }
}

// Convenience function for easy initialization
function initWeightPenaltyWidget(
    containerId = 'weight-penalty-container',
    operatorId = 'weight-penalty-operator', 
    pairsContainerId = 'weight-pairs-container',
    addButtonId = 'add-weight-pair',
    hiddenInputId = 'id_weight_penalty'
) {
    return new WeightPenaltyWidget(containerId, operatorId, pairsContainerId, addButtonId, hiddenInputId);
}