from agents.screener_agent import run_screener

if __name__ == "__main__":
    try:
        results = run_screener()
        print("Screening Results:")
        for result in results:
            print(f"{result['ticker']} - Drop: {result['drop_pct']:.1f}%, RSI: {result['rsi']:.1f}, Volume: {result['volume_ratio']:.1f}")
            print(f"  News: {', '.join(result['news'])}")
            print(f"  Analysis: {result['analysis']}")
            print()

        print(f"Found {len(results)} candidates")

    except Exception as e:
        print(f"Error: {str(e)}")
