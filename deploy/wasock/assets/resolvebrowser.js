function resolveBrowser(browserInfo, Browsers) {
    const name = browserInfo[1];

    switch (browserInfo[0]) {
        case "windows": return Browsers.windows(name);
        case "macos": return Browsers.macOS(name);
        default: return Browsers.ubuntu(name);
    }
}

module.exports = {
    resolveBrowser
};