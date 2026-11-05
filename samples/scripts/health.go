package main

import (
	"fmt"
	"net/http"
	"os"
	"time"
)

// check answers whether the endpoint replies with 2xx within the timeout.
func check(url string, timeout time.Duration) error {
	client := &http.Client{Timeout: timeout}
	resp, err := client.Get(url)
	if err != nil {
		return fmt.Errorf("get %s: %w", url, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		return fmt.Errorf("%s: status %d", url, resp.StatusCode)
	}
	return nil
}

func main() {
	if err := check(os.Args[1], 5*time.Second); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
