const appUser = _getEnv("MONGO_APP_USERNAME") || "app_trust_user";
const appPassword = _getEnv("MONGO_APP_PASSWORD");
const appDatabase = _getEnv("MONGO_APP_DATABASE") || "newsdb";

if (!appPassword) {
  throw new Error("MONGO_APP_PASSWORD is required to create the MongoDB application user");
}

const appDb = db.getSiblingDB(appDatabase);

if (appDb.getUser(appUser)) {
  appDb.updateUser(appUser, {
    pwd: appPassword,
    roles: [{ role: "readWrite", db: appDatabase }],
  });
} else {
  appDb.createUser({
    user: appUser,
    pwd: appPassword,
    roles: [{ role: "readWrite", db: appDatabase }],
  });
}
