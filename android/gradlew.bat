@echo off
rem Gradle start-up script wrapper (minimal, invokes gradle-wrapper.jar with the JVM/JDK we installed).
setlocal
set DIRNAME=%~dp0
if "%DIRNAME%"=="" set DIRNAME=.
set JAVA_HOME=%JAVA_HOME%
"%JAVA_HOME%\bin\java" -classpath "%DIRNAME%gradle\wrapper\gradle-wrapper.jar" org.gradle.wrapper.GradleWrapperMain %*
endlocal
