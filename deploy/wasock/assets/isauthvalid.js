const fs = require("fs");
const path = require("path");

function getFileLength(folderPath) {
    return fs.readdirSync(folderPath).filter(file => {
        return fs.statSync(path.join(folderPath, file)).isFile();
    }).length;
}

function isAuthValid(authPath) {
    const credsPath = path.join(authPath, "creds.json");
    const authLength = getFileLength(authPath);

    if (authLength <= 1) {
        return false;
    }

    if (!fs.existsSync(credsPath)) {
        return false;
    }

    try {
        JSON.parse(fs.readFileSync(credsPath, "utf8"));
        return true;
    } catch {
        return false;
    }
}

module.exports = {
    isAuthValid
};