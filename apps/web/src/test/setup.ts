import '@testing-library/jest-dom/vitest'

// jsdom does not implement Element.scrollTo; the chat viewport autoscrolls on update.
Element.prototype.scrollTo = () => {}
