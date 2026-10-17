# Gradle build with increased heap
# Use local gradle-8.2 distribution
export GRADLE_USER_HOME='./.gradle'
export GRADLE_OPTS='-Xmx4096m'
export ORG_GRADLE_OPTS='-Xmx4096m'