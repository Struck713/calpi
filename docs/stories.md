# calpi — stories

This document breaks the [high-level plan](plan.md) into user stories. Each story has a name, a short description, a priority, and the stories that must be finished before it can be completed. The stories will be expanded with acceptance criteria and implementation notes later.

## Platform

- **Hardware:** Raspberry Pi 3B driving an HDMI screen at 1920x1080. A non-touch portable monitor is used for testing now, and a touchscreen will be used later.
- **OS:** Raspberry Pi OS Lite (no desktop), booting straight into the app under the `cage` Wayland kiosk compositor, managed by systemd.
- **App:** Python with GTK (PyGObject), running fullscreen.
- **Calendar sync:** CalDAV, starting with iCloud and an app-specific password.

## Priority Levels

| Priority | Meaning |
|---|---|
| **P0** | Must have. The device isn't usable without it. |
| **P1** | Needed before the device counts as finished and ready to run every day. |
| **P2** | Optional extras to add once the core is solid. |

A P0 story is never blocked by a lower-priority story. **Blocked by** lists the stories that must be finished before this story can be completed.

---

## Epic 1: Foundation

| ID | Story | Description | Priority | Blocked by |
|---|---|---|---|---|
| US-01 | Kiosk OS provisioning | As the owner, I want the Pi to boot straight into the app, full screen, with no desktop, no cursor and no screen blanking. | P0 | — |
| US-02 | App skeleton | As a developer, I want a minimal fullscreen GTK app that runs on the Pi and in the devcontainer without a display, so UI work can start. | P0 | — |
| US-03 | Deploy workflow | As a developer, I want to push the app to the Pi, restart it, read its logs and take a screenshot of the screen from the dev machine. | P0 | US-01, US-02 |
| US-04 | Local event store | As a user, I want events saved on the device so the calendar appears right away at boot and stays visible offline. Includes a sample-data loader for development. | P0 | US-02 |
| US-05 | Settings store | As a user, I want my settings saved on the device so they survive restarts and power cuts. | P0 | US-02 |
| US-06 | Month grid | As a user, I want the current month shown as a grid with today clearly marked. | P0 | US-02 |
| US-07 | Events in the grid | As a user, I want each day's events shown in its cell, colored by calendar, including all-day and multi-day events. | P0 | US-04, US-06 |
| US-08 | Month navigation | As a user, I want to move to the previous or next month, and have the view return to the current month after a period of inactivity. | P0 | US-06 |
| US-09 | Day detail view | As a user, I want to open a day and see all of its events in full when they don't fit in the grid cell. | P1 | US-07 |
| US-10 | Midnight rollover | As a user, I want "today" and the displayed month to update on their own when the date changes. | P0 | US-06 |
| US-11 | Pointer and touch input | As a user, I want every control to work with touch as well as a mouse and keyboard, so the app works on both the test monitor and the touchscreen. | P0 | US-02 |
| US-12 | Crash and power-loss recovery | As the owner, I want the app to restart itself after a crash and come back cleanly after a power cut, without wearing out the SD card. | P0 | US-01 |

## Epic 2: Calendar Syncing

| ID | Story | Description | Priority | Blocked by |
|---|---|---|---|---|
| US-13 | Secure credential storage | As a user, I want my account sign-in details stored securely on the device, never in plain text. | P0 | US-05 |
| US-14 | iCloud account connection | As a user, I want to sign in to iCloud with my Apple ID and an app-specific password, and have the device find my calendars. | P0 | US-13 |
| US-15 | Event fetching and parsing | As a user, I want events for the visible date range downloaded and understood correctly, including recurring events, exceptions and time zones. | P0 | US-04, US-14 |
| US-16 | Scheduled background sync | As a user, I want events refreshed on my chosen schedule without the display stuttering or freezing. | P0 | US-05, US-15 |
| US-17 | Offline resilience | As a user, I want the calendar to keep showing the last synced events when the network is down, and to retry quietly until it's back. | P0 | US-16 |
| US-18 | Sync status tracking | As a user, I want the app to record when each calendar last synced and why a sync failed, if it did. | P1 | US-16 |
| US-19 | Manual refresh | As a user, I want to trigger a sync right away instead of waiting for the next scheduled one. | P1 | US-16 |
| US-20 | Additional providers | As a user, I want to add calendars from other providers, such as Google, alongside iCloud. | P2 | US-15 |

## Epic 3: Setup and Settings

| ID | Story | Description | Priority | Blocked by |
|---|---|---|---|---|
| US-21 | On-screen keyboard | As a user, I want an on-screen keyboard for entering text such as passwords without a physical keyboard. | P0 | US-11 |
| US-22 | Settings shell | As a user, I want a settings area, reached from the main screen, with clear sections and a way back to the calendar. | P0 | US-05, US-11 |
| US-23 | Wi-Fi scan and connect | As a user, I want to see nearby Wi-Fi networks, pick one, enter its password and connect. | P0 | US-01, US-21, US-22 |
| US-24 | Saved network management | As a user, I want to see the current connection's status and forget saved networks. | P1 | US-23 |
| US-25 | Account management | As a user, I want to add and remove calendar accounts from Settings. | P0 | US-14, US-21, US-22 |
| US-26 | Calendar customization | As a user, I want to show, hide, rename and recolor individual calendars. | P1 | US-07, US-25 |
| US-27 | Sync settings | As a user, I want to choose how often events refresh. | P0 | US-16, US-22 |
| US-28 | Regional preferences | As a user, I want to set the time zone, the first day of the week, and 12- or 24-hour time. | P0 | US-06, US-22 |
| US-29 | Brightness control | As a user, I want to adjust the screen's brightness from Settings, where the display hardware allows it. | P1 | US-22 |
| US-30 | Overnight dim and sleep schedule | As a user, I want the display to dim or turn off overnight on a schedule I choose, and wake when touched. | P1 | US-29 |
| US-31 | Status screen | As a user, I want one screen that shows the network status, the last sync time and any errors, in plain language. | P1 | US-18, US-22, US-23 |
| US-32 | First-time setup wizard | As a new user, I want a guided setup on first boot that covers Wi-Fi, preferences, account sign-in, calendar selection and refresh timing, with every step skippable. The dimming step is added once US-30 is done. | P0 | US-23, US-25, US-27, US-28 |
| US-33 | iCloud setup guide | As a user, I want a short guide explaining how to create an app-specific password for the device. | P1 | US-25 |

## Epic 4: Touch and Polish

| ID | Story | Description | Priority | Blocked by |
|---|---|---|---|---|
| US-34 | Touchscreen bring-up | As the owner, I want the touchscreen detected, correctly oriented and accurate when it replaces the test monitor. | P1 | US-01, US-11 |
| US-35 | Touch gestures | As a user, I want to swipe between months on the touchscreen. | P2 | US-08, US-34 |
| US-36 | Performance targets | As a user, I want the app to start quickly and change months and screens instantly, with measured targets checked on the Pi. | P1 | US-07, US-16 |
| US-37 | Long-running stability | As the owner, I want the device to run for weeks without slowing down, using more memory, or needing a restart. | P1 | US-16, US-36 |
| US-38 | User-facing error handling | As a user, I want problems such as a wrong password, no network or an expired account to show as clear messages with a suggested fix. | P1 | US-18 |

## Epic 5: Extras

| ID | Story | Description | Priority | Blocked by |
|---|---|---|---|---|
| US-39 | Week view | As a user, I want a week view that shows more detail than the month grid. | P2 | US-07 |
| US-40 | Agenda view | As a user, I want a scrolling list of upcoming events. | P2 | US-07 |
| US-41 | Weather | As a user, I want today's weather and a short forecast shown alongside the calendar. | P2 | US-06, US-23 |

---

## Critical Path

These are the P0 stories that lead to a usable device, in dependency order:

1. **US-01, US-02:** a kiosk OS and the app skeleton (these can run in parallel)
2. **US-03, US-04, US-05, US-06, US-11, US-12:** deploying, storage, the grid, input, and recovery
3. **US-07, US-08, US-10, US-13, US-21, US-22:** events in the grid, navigation, credentials, and the settings shell
4. **US-14 → US-15 → US-16 → US-17:** the iCloud sync pipeline
5. **US-23, US-25, US-27, US-28:** Wi-Fi, accounts, sync settings, and preferences
6. **US-32:** the first-time setup wizard, which completes the P0 set
