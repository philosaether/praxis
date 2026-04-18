import Shepherd from 'shepherd.js';

// Only start if this is a new user
const container = document.querySelector('.container');
if (container && container.dataset.isNewUser === 'true') {
  // Wait for DOM to be fully ready
  document.addEventListener('DOMContentLoaded', () => startTutorial());
}

function startTutorial() {
  const container = document.querySelector('.container');
  container.classList.add('tutorial-active');

  // Track state across steps
  let createdPriorityName = '';

  // Track active listeners for cleanup on cancel
  const activeListeners = [];

  function addTrackedListener(target, event, handler) {
    target.addEventListener(event, handler);
    activeListeners.push({ target, event, handler });
  }

  function removeAllListeners() {
    for (const { target, event, handler } of activeListeners) {
      target.removeEventListener(event, handler);
    }
    activeListeners.length = 0;
  }

  // Poll helper with timeout guard (10s max)
  function pollFor(conditionFn, resolve, intervalMs) {
    const start = Date.now();
    const check = setInterval(() => {
      if (conditionFn()) {
        clearInterval(check);
        resolve();
      } else if (Date.now() - start > 10000) {
        clearInterval(check);
        resolve(); // Don't hang — advance even if condition isn't met
      }
    }, intervalMs || 100);
  }

  const tour = new Shepherd.Tour({
    useModalOverlay: true,
    defaultStepOptions: {
      scrollTo: true,
      cancelIcon: { enabled: true },
      classes: 'praxis-tutorial',
      canClickTarget: true,
      modalOverlayOpeningPadding: 4,
    },
  });

  // When tour completes or is cancelled, clean up
  tour.on('complete', () => {
    container.classList.remove('tutorial-active');
    removeAllListeners();
    fetch('/tutorial-completed', { method: 'POST' });
  });
  tour.on('cancel', () => {
    container.classList.remove('tutorial-active');
    removeAllListeners();
  });

  // =========================================================================
  // Step 1: Orient
  // =========================================================================
  tour.addStep({
    id: 'welcome',
    text: '<strong>Welcome to Praxis</strong><br>Let\'s get you set up.',
    buttons: [{ text: 'Let\'s go', action: tour.next }],
  });

  // =========================================================================
  // Step 2: Make a task — point to FAB
  // =========================================================================
  tour.addStep({
    id: 'fab-task',
    attachTo: { element: '#fab-button', on: 'top' },
    text: 'Click here to make a new task.',
    advanceOn: { selector: '#fab-button', event: 'click' },
    buttons: [],
  });

  // =========================================================================
  // Step 3: Give it a name
  // =========================================================================
  tour.addStep({
    id: 'name-task',
    attachTo: { element: '#quick-add-backdrop .modal', on: 'bottom' },
    text: 'Give your task a name, then click "Add Task."',
    buttons: [],
    beforeShowPromise: () => new Promise(resolve => {
      pollFor(() => {
        const input = document.getElementById('quick-add-name');
        return input && input.offsetParent !== null;
      }, resolve);
    }),
    when: {
      show: () => {
        const handler = () => {
          document.body.removeEventListener('taskCreated', handler);
          tour.next();
        };
        addTrackedListener(document.body, 'taskCreated', handler);
      },
    },
  });

  // =========================================================================
  // Step 4: Introduce task queue
  // =========================================================================
  tour.addStep({
    id: 'task-queue',
    attachTo: { element: '#item-list', on: 'right' },
    text: 'This is your task queue. Later on, you can customize it so it only shows you tasks you want to work on.',
    buttons: [{ text: 'Ok, cool', action: tour.next }],
    beforeShowPromise: () => new Promise(resolve => {
      pollFor(() => !!document.querySelector('.task-row'), resolve);
    }),
  });

  // =========================================================================
  // Step 5: Introduce task detail — click the task row
  // =========================================================================
  tour.addStep({
    id: 'click-task',
    attachTo: { element: '.task-row', on: 'bottom' },
    text: 'Here\'s the task you just made. Click it to view details.',
    advanceOn: { selector: '.task-row .task-content', event: 'click' },
    buttons: [],
  });

  // =========================================================================
  // Step 6: Introduce edit mode
  // =========================================================================
  tour.addStep({
    id: 'edit-mode',
    attachTo: { element: '#detail-content .actions-left .btn-primary', on: 'bottom' },
    canClickTarget: false,
    text: 'Later on, you can use Edit Mode to add details to your task. For now, let\'s keep moving.',
    buttons: [{ text: 'Good idea', action: tour.next }],
    beforeShowPromise: () => new Promise(resolve => {
      pollFor(() => {
        const btn = document.querySelector('#detail-content .actions-left .btn-primary');
        return btn && btn.offsetParent !== null;
      }, resolve);
    }),
  });

  // =========================================================================
  // Step 7: Introduce priorities
  // =========================================================================
  tour.addStep({
    id: 'priorities-nav',
    attachTo: { element: '#priorities-nav-btn', on: 'top' },
    text: 'Praxis organizes your work based on what\'s most important to you. Click here to see your priorities.',
    advanceOn: { selector: '#priorities-nav-btn', event: 'click' },
    buttons: [],
  });

  // =========================================================================
  // Step 8: Make a priority — point to FAB
  // =========================================================================
  tour.addStep({
    id: 'fab-priority',
    attachTo: { element: '#fab-button', on: 'top' },
    text: 'In priority mode, the quick-add button will make a new priority.',
    advanceOn: { selector: '#fab-button', event: 'click' },
    buttons: [],
    beforeShowPromise: () => new Promise(resolve => {
      pollFor(() => window.currentMode === 'priorities', resolve);
    }),
  });

  // =========================================================================
  // Step 9: Name the priority — with Done button
  // =========================================================================
  tour.addStep({
    id: 'name-priority',
    attachTo: { element: '#quick-add-priority-name', on: 'bottom' },
    text: 'What\'s most important to you? Type it in here.',
    buttons: [{
      text: 'Done',
      action: () => {
        const input = document.getElementById('quick-add-priority-name');
        createdPriorityName = input ? input.value.trim() : 'that';
        tour.next();
      },
    }],
    beforeShowPromise: () => new Promise(resolve => {
      pollFor(() => {
        const input = document.getElementById('quick-add-priority-name');
        return input && input.offsetParent !== null;
      }, resolve);
    }),
  });

  // =========================================================================
  // Step 10: Introduce more options
  // =========================================================================
  tour.addStep({
    id: 'more-options',
    attachTo: { element: '.priority-modal .more-options summary', on: 'top' },
    text: '', // Set dynamically in beforeShow
    buttons: [],
    beforeShowPromise: () => new Promise(resolve => {
      const name = createdPriorityName || 'that';
      const step = tour.steps.find(s => s.id === 'more-options');
      step.updateStepOptions({
        text: `"${name}?" Hey, you do you. Let's make sure we capture how important it is properly. Tap "More options."`,
      });
      resolve();
    }),
    when: {
      show: () => {
        pollFor(() => {
          const details = document.querySelector('.priority-modal .more-options');
          return details && details.open;
        }, () => tour.next(), 200);
      },
    },
  });

  // =========================================================================
  // Step 11: Set the type to Value
  // =========================================================================
  tour.addStep({
    id: 'set-type',
    attachTo: { element: '#quick-add-priority-type', on: 'bottom' },
    text: 'Use this dropdown to make your priority a <strong>Value</strong>. Values are the most important kind of priority in Praxis.',
    buttons: [],
    when: {
      show: () => {
        const select = document.getElementById('quick-add-priority-type');
        if (select) {
          const handler = () => {
            if (select.value === 'value') {
              select.removeEventListener('change', handler);
              tour.next();
            }
          };
          addTrackedListener(select, 'change', handler);
        }
      },
    },
  });

  // =========================================================================
  // Step 12: Save the priority
  // =========================================================================
  tour.addStep({
    id: 'save-priority',
    attachTo: { element: '.priority-modal .btn-primary', on: 'top' },
    text: 'Click here to save your new Value.',
    buttons: [],
    when: {
      show: () => {
        const handler = () => {
          document.body.removeEventListener('priorityCreated', handler);
          tour.next();
        };
        addTrackedListener(document.body, 'priorityCreated', handler);
      },
    },
  });

  // =========================================================================
  // Step 13: Introduce the tree
  // =========================================================================
  tour.addStep({
    id: 'tree-intro',
    attachTo: { element: '.tree-pane', on: 'right' },
    text: 'As you add more priorities, you can organize them here by dragging. Whatever\'s on top gets the most attention in your task queue.',
    buttons: [{ text: 'Cool!', action: tour.next }],
    beforeShowPromise: () => new Promise(resolve => {
      pollFor(() => {
        return document.querySelector('.tree-pane') || document.querySelector('.tree-node');
      }, resolve, 200);
    }),
  });

  // =========================================================================
  // Step 14: Navigate to inbox
  // =========================================================================
  tour.addStep({
    id: 'inbox-nav',
    attachTo: { element: '#inbox-nav-btn', on: 'right' },
    text: 'Almost done. Click here to see your task inbox.',
    advanceOn: { selector: '#inbox-nav-btn', event: 'click' },
    buttons: [],
  });

  // =========================================================================
  // Step 15: Introduce inbox
  // =========================================================================
  tour.addStep({
    id: 'inbox-intro',
    attachTo: { element: '#item-list', on: 'right' },
    text: 'Unprioritized tasks will always show up here, so you know where to find them. Go ahead and click that task to give it a home.',
    buttons: [],
    beforeShowPromise: () => new Promise(resolve => {
      pollFor(() => {
        return window.currentMode === 'inbox' && document.querySelector('.task-row');
      }, resolve);
    }),
    when: {
      show: () => {
        const itemList = document.getElementById('item-list');
        const handler = (e) => {
          if (e.target.closest('.task-row')) {
            itemList.removeEventListener('click', handler);
            tour.next();
          }
        };
        addTrackedListener(itemList, 'click', handler);
      },
    },
  });

  // =========================================================================
  // Step 16: Triage — pick a priority
  // =========================================================================
  tour.addStep({
    id: 'triage',
    attachTo: { element: '.inbox-picker.open', on: 'bottom' },
    text: 'Select your priority to file this task.',
    buttons: [],
    beforeShowPromise: () => new Promise(resolve => {
      pollFor(() => !!document.querySelector('.inbox-picker.open'), resolve);
    }),
    when: {
      show: () => {
        const handler = () => {
          document.removeEventListener('prioritySelected', handler);
          setTimeout(() => tour.next(), 400); // Wait for fade-out animation
        };
        addTrackedListener(document, 'prioritySelected', handler);
      },
    },
  });

  // =========================================================================
  // Step 17: Done!
  // =========================================================================
  tour.addStep({
    id: 'done',
    text: '<strong>You\'re all set!</strong><br><br>' +
      'Here\'s what to remember:<br>' +
      '&bull; Tap <strong>+</strong> to capture tasks anytime<br>' +
      '&bull; Your <strong>inbox</strong> holds unsorted tasks — tap to sort them<br>' +
      '&bull; <strong>Priorities</strong> organize what matters most',
    buttons: [{ text: 'Got it', action: tour.complete }],
  });

  // Start the tour
  tour.start();
}
